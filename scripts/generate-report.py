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


def build_history(results):
    """Build version history for the chart."""
    history = []
    for r in results:
        entry = {
            "version": r.get("quaid_version", "unknown"),
            "date": r.get("date", ""),
            "benchmarks": {}
        }
        if "dab" in r:
            entry["benchmarks"]["dab"] = {
                "total": r["dab"].get("total_score"),
                "max": r["dab"].get("max_score"),
                "pct": round(r["dab"]["total_score"] / r["dab"]["max_score"] * 100, 1)
            }
        if "gbrain_evals" in r:
            entry["benchmarks"]["gbrain_evals"] = {
                "p_at_5": r["gbrain_evals"].get("p_at_5"),
                "r_at_5": r["gbrain_evals"].get("r_at_5"),
            }
        history.append(entry)
    return history


def main():
    results = load_results()
    history = build_history(results)
    latest = results[-1] if results else None

    report = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "latest": latest,
        "history": history,
        "reference": REFERENCE_SCORES,
        "total_runs": len(results),
    }

    out_path = SITE_DATA_DIR / "report.json"
    out_path.write_text(json.dumps(report, indent=2))
    print(f"Report written to {out_path}")
    print(f"Total runs: {len(results)}")
    if latest:
        print(f"Latest: quaid {latest.get('quaid_version')} on {latest.get('date')}")


if __name__ == "__main__":
    main()
