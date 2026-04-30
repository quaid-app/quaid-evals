#!/usr/bin/env python3
"""
generate-report.py - Aggregate benchmark result JSONs into a single summary
for the Astro site to consume.
"""
import json
from datetime import UTC, datetime
from pathlib import Path

RESULTS_DIR = Path("results")
SITE_DATA_DIR = Path("site/src/data")
SITE_DATA_DIR.mkdir(parents=True, exist_ok=True)

# Reference scores from published benchmarks (hardcoded, update as new data lands)
REFERENCE_SCORES = {
    "gbrain": {
        "label": "GBrain (Garry Tan)",
        "source": "https://x.com/garrytan/status/2048503081911128119",
        "date": "2026-04-27",
        "gbrain_evals": {"p_at_5": 49.1, "r_at_5": 97.9},
        "notes": "145 queries, Opus-generated corpus, 17,888 pages. Graph layer = +31pts precision."
    },
    "mem0_v3": {
        "label": "Mem0 v3",
        "source": "https://mem0.ai",
        "date": "2026-04-01",
        "beam": {"score_1m": 64.1, "score_10m": 48.6},
        "locomo": {
            "single_hop": 97.0,
            "multi_hop": 93.0,
            "temporal": 93.0,
            "open_domain": 76.0,
            "overall": 91.6,
        },
        "longmemeval": {"score": 93.4},
        "notes": "~7K tokens per retrieval vs 25K+ for full-context."
    },
    "hindsight": {
        "label": "Hindsight",
        "source": None,
        "date": None,
        "beam": {"score_1m": "TBD", "score_10m": "SOTA"},
        "locomo": {"single_hop": "n/a", "multi_hop": "n/a", "temporal": "n/a", "overall": "SOTA"},
        "notes": "Headline positioning from published benchmark materials. Public per-type LoCoMo breakdown is not included here."
    }
}


def semver_parts(version):
    import re

    return [int(part) for part in re.findall(r"\d+", str(version))]


def normalize_percent(value, digits=1):
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, str):
        return value

    value = float(value)
    if 0.0 <= value <= 1.0:
        value *= 100
    return round(value, digits)


def load_json(path):
    try:
        return json.loads(path.read_text())
    except Exception as exc:
        print(f"Warning: could not parse {path}: {exc}")
        return None


def load_results():
    results = []
    for f in sorted(RESULTS_DIR.glob("*.json")):
        data = load_json(f)
        if data is not None:
            results.append(data)
    return results


def load_dab_v2_results():
    """Load DAB v2 full results."""
    runs = {}
    for f in sorted(RESULTS_DIR.glob("dab-v2-full-*.json")):
        data = load_json(f)
        if data is None:
            continue
        key = (data.get("system", "?"), data.get("version", "?"), data.get("date", ""))
        runs[key] = data
    return list(runs.values())


def extract_locomo_scores(result):
    payload = result.get("locomo", {})
    by_type = payload.get("by_type", {})

    def type_avg(*names):
        for name in names:
            if name in by_type:
                return normalize_percent(by_type[name].get("avg"))
        return None

    return {
        "overall": normalize_percent(payload.get("overall")),
        "pass_rate": normalize_percent(payload.get("pass_rate")),
        "total_questions": payload.get("total_questions"),
        "single_hop": type_avg("single-hop", "single_hop", "single hop"),
        "multi_hop": type_avg("multi-hop", "multi_hop", "multi hop"),
        "temporal": type_avg("temporal"),
        "open_domain": type_avg("open-domain", "open_domain", "open domain"),
    }


def extract_beam_scores(result):
    payload = result.get("beam")
    if not isinstance(payload, dict):
        payload = result

    tiers = payload.get("tiers", {})

    def read_score(*keys):
        for key in keys:
            value = payload.get(key)
            if value is not None:
                return normalize_percent(value)
        return None

    def read_tier_score(*tier_keys):
        for key in tier_keys:
            tier = tiers.get(key)
            if isinstance(tier, dict):
                for score_key in ("score", "overall", "accuracy"):
                    if tier.get(score_key) is not None:
                        return normalize_percent(tier[score_key])
            elif tier is not None:
                return normalize_percent(tier)
        return None

    return {
        "score_100k": read_score("score_100k", "beam_100k") or read_tier_score("100k", "tier_100k"),
        "score_1m": read_score("score_1m", "beam_1m") or read_tier_score("1m", "tier_1m"),
        "score_10m": read_score("score_10m", "beam_10m") or read_tier_score("10m", "tier_10m"),
    }


def load_benchmark_summary(pattern, extract_scores, version_field="quaid_version"):
    runs = []
    for path in sorted(RESULTS_DIR.glob(pattern)):
        data = load_json(path)
        if data is None:
            continue
        runs.append(
            {
                "version": data.get(version_field) or data.get("version") or "unknown",
                "date": data.get("date"),
                "scores": extract_scores(data),
                "status": "measured",
            }
        )

    runs.sort(key=lambda run: (run.get("date", ""), semver_parts(run.get("version", "0"))))

    latest = dict(runs[-1]) if runs else {
        "version": None,
        "date": None,
        "scores": None,
        "status": "pending",
    }
    latest["all_runs"] = runs
    return latest


def build_history(results):
    """Build version history - merge benchmark snapshots by version+date."""
    runs = {}
    for r in results:
        version = r.get("quaid_version") or r.get("version") or "unknown"
        key = (version, r.get("date", ""))
        if key not in runs:
            runs[key] = {"version": key[0], "date": key[1], "benchmarks": {}}
        benchmark = r.get("benchmark", "")
        if benchmark == "dab":
            runs[key]["dab"] = r
            runs[key]["benchmarks"]["dab"] = {
                "total": r.get("total_score"),
                "max": r.get("max_score"),
                "pct": round(r["total_score"] / r["max_score"] * 100, 1)
            }
        elif benchmark == "gbrain-evals":
            runs[key]["gbrain_evals"] = r.get("gbrain_evals", {})
            ge = r.get("gbrain_evals", {})
            runs[key]["benchmarks"]["gbrain_evals"] = {
                "p_at_5": ge.get("p_at_5"),
                "r_at_5": ge.get("r_at_5"),
            }
        elif benchmark == "locomo":
            scores = extract_locomo_scores(r)
            runs[key]["locomo"] = r.get("locomo", {})
            runs[key]["benchmarks"]["locomo"] = {
                "overall": scores.get("overall"),
                "pass_rate": scores.get("pass_rate"),
                "status": "measured",
            }
        elif benchmark == "beam":
            scores = extract_beam_scores(r)
            runs[key]["beam"] = r.get("beam", {})
            runs[key]["benchmarks"]["beam"] = {
                "score_1m": scores.get("score_1m"),
                "score_10m": scores.get("score_10m"),
                "status": "measured",
            }

    return sorted(runs.values(), key=lambda run: (run.get("date", ""), semver_parts(run.get("version", "0"))))


def main():
    results = load_results()
    history = build_history(results)
    latest = history[-1] if history else None

    # DAB v2 results
    dab_v2_runs = load_dab_v2_results()
    dab_v2_latest = sorted(dab_v2_runs, key=lambda x: (
        x.get("date", ""), semver_parts(x.get("version", "0"))
    ))[-1] if dab_v2_runs else None
    locomo = load_benchmark_summary("locomo-*.json", extract_locomo_scores)
    beam = load_benchmark_summary("beam-*.json", extract_beam_scores)

    report = {
        "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "latest": latest,
        "history": history,
        "locomo": locomo,
        "beam": beam,
        "dab_v2": {
            "latest": dab_v2_latest,
            "all_runs": dab_v2_runs,
        },
        "reference": REFERENCE_SCORES,
        "total_runs": len(history),
    }

    out_path = SITE_DATA_DIR / "report.json"
    out_path.write_text(json.dumps(report, indent=2))
    print(f"Report written to {out_path}")
    print(f"Total raw result files: {len(results)}")
    if latest:
        print(f"Latest merged release snapshot: quaid {latest.get('version')} on {latest.get('date')}")


if __name__ == "__main__":
    main()
