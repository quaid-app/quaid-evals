#!/usr/bin/env python3
"""
generate-report.py - Aggregate benchmark result JSONs into a single summary
for the Astro site to consume.
"""
import json
import os
from pathlib import Path
from datetime import datetime

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
        "locomo": {"score": 91.6},
        "longmemeval": {"score": 93.4},
        "notes": "~7K tokens per retrieval vs 25K+ for full-context."
    }
}


def load_results():
    results = []
    for f in sorted(RESULTS_DIR.glob("*.json")):
        try:
            data = json.loads(f.read_text())
            results.append(data)
        except Exception as e:
            print(f"Warning: could not parse {f}: {e}")
    return results


def load_dab_v2_results():
    """Load DAB v2 full results."""
    runs = {}
    for f in sorted(RESULTS_DIR.glob("dab-v2-full-*.json")):
        try:
            data = json.loads(f.read_text())
            key = (data.get("system", "?"), data.get("version", "?"), data.get("date", ""))
            runs[key] = data
        except Exception as e:
            print(f"Warning: could not parse {f}: {e}")
    return list(runs.values())


def build_history(results):
    """Build version history - merge DAB and gbrain-evals by version+date."""
    # Group by (version, date)
    runs = {}
    for r in results:
        key = (r.get("quaid_version", "unknown"), r.get("date", ""))
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

    # Sort by date then version (numeric semver sort)
    def version_key(x):
        import re
        v = x.get("version", "0.0.0")
        parts = re.findall(r'\d+', v)
        return (x.get("date", ""), [int(p) for p in parts])

    history = sorted(runs.values(), key=version_key)
    return history


def main():
    results = load_results()
    history = build_history(results)
    latest = history[-1] if history else None
    
    # DAB v2 results
    dab_v2_runs = load_dab_v2_results()
    import re
    dab_v2_latest = sorted(dab_v2_runs, key=lambda x: (
        x.get("date",""), [int(p) for p in re.findall(r'\d+', x.get("version","0"))]
    ))[-1] if dab_v2_runs else None

    report = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "latest": latest,
        "history": history,
        "dab_v2": {
            "latest": dab_v2_latest,
            "all_runs": dab_v2_runs,
        },
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "latest": latest,
        "history": history,
        "reference": REFERENCE_SCORES,
        "total_runs": len(history),
    }

    out_path = SITE_DATA_DIR / "report.json"
    out_path.write_text(json.dumps(report, indent=2))
    print(f"Report written to {out_path}")
    print(f"Total runs: {len(results)}")
    if latest:
        print(f"Latest: quaid {latest.get('quaid_version')} on {latest.get('date')}")


if __name__ == "__main__":
    main()
