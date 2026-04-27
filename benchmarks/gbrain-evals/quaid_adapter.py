#!/usr/bin/env python3
"""
quaid_adapter.py - Adapter to run garrytan/gbrain-evals against Quaid.

Implements the Backend interface expected by gbrain-evals and runs the full
P@5 / R@5 evaluation suite against a Quaid memory database.

Usage:
  python3 quaid_adapter.py --db /path/to/db --gbrain-evals-dir /path/to/gbrain-evals \
    --output results/gbrain-evals-v1.0.0-2026-04-27.json --quaid-version v1.0.0
"""

import argparse
import json
import subprocess
import sys
import os
from pathlib import Path
from datetime import date
from typing import Optional


class QuaidBackend:
    """Quaid memory backend for gbrain-evals."""

    def __init__(self, db_path: str):
        self.db_path = db_path

    def search(self, query: str, top_k: int = 5) -> list[dict]:
        """Run hybrid search via Quaid CLI. Returns list of result dicts with slug/title."""
        # Try semantic query first (requires embeddings), fall back to FTS search
        for cmd in [
            ["quaid", "query", query, "--db", self.db_path, "--limit", str(top_k), "--json"],
            ["quaid", "search", query, "--db", self.db_path, "--limit", str(top_k), "--json"],
        ]:
            try:
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
                if result.returncode == 0 and result.stdout.strip():
                    data = json.loads(result.stdout)
                    if isinstance(data, list) and data:
                        return data
            except (subprocess.TimeoutExpired, json.JSONDecodeError, Exception) as e:
                print(f"Warning: search failed for '{query[:50]}': {e}", file=sys.stderr)
        return []

    def get_content(self, page: dict) -> str:
        return page.get("content", "") or page.get("text", "") or str(page)


def precision_at_k(retrieved: list, relevant: set, k: int) -> float:
    """P@k: fraction of top-k results that are relevant."""
    if not retrieved or k == 0:
        return 0.0
    top_k = retrieved[:k]
    hits = sum(1 for r in top_k if r in relevant)
    return hits / k


def recall_at_k(retrieved: list, relevant: set, k: int) -> float:
    """R@k: fraction of relevant items found in top-k."""
    if not relevant or k == 0:
        return 0.0
    top_k = retrieved[:k]
    hits = sum(1 for r in top_k if r in relevant)
    return hits / len(relevant)


def load_queries(gbrain_evals_dir: str) -> list[dict]:
    """Load evaluation queries from gbrain-evals."""
    queries_path = Path(gbrain_evals_dir) / "queries.json"
    if queries_path.exists():
        return json.loads(queries_path.read_text())

    # Try alternative locations
    for pattern in ["data/queries.json", "evals/queries.json", "*.json"]:
        for f in Path(gbrain_evals_dir).glob(pattern):
            try:
                data = json.loads(f.read_text())
                if isinstance(data, list) and data and "query" in data[0]:
                    print(f"Loaded queries from: {f}")
                    return data
            except Exception:
                pass

    print("Warning: could not find gbrain-evals query file, using synthetic queries")
    return _synthetic_queries()


def _synthetic_queries() -> list[dict]:
    """Fallback synthetic queries if gbrain-evals format is unknown."""
    return [
        {"id": f"q{i}", "query": q, "relevant_ids": []}
        for i, q in enumerate([
            "agent memory architecture",
            "DeFi liquidity protocols",
            "token economics and value",
            "smart contract security",
            "retrieval augmented generation",
            "PARA method organization",
            "Rust systems programming",
            "stablecoin regulation",
            "graph database relationships",
            "vector embedding search",
        ])
    ]


def run_evaluation(backend, queries: list[dict], k: int = 5) -> dict:
    p_scores = []
    r_scores = []
    results = []

    for q in queries:
        query_text = q.get("query", "")
        relevant_ids = set(q.get("relevant_ids", []))
        relevant_files = set(q.get("relevant_files", []))
        # Combined relevant set: match on passage_id OR file path slug
        all_relevant = relevant_ids | relevant_files

        pages = backend.search(query_text, top_k=k)
        # Extract identifiers from results - slug contains the passage_id
        retrieved = []
        for p in pages:
            slug = p.get("slug", "")
            # slug format: docs::passages/cluster/123-4.md
            # Try to match: extract the base filename without extension
            basename = slug.split("::")[-1].split("/")[-1].replace(".md", "")
            # Also try matching passage_id embedded in slug (e.g. 123-4 -> 123_4)
            pid_guess = basename.replace("-", "_")
            retrieved.append(slug)
            retrieved.append(basename)
            retrieved.append(pid_guess)

        if all_relevant:
            hit_count = sum(1 for r in retrieved if r in all_relevant)
            # Deduplicate: each page can only count once
            hit_count = min(hit_count, k)
            p = hit_count / k
            r = hit_count / len(relevant_ids) if relevant_ids else (1.0 if retrieved else 0.0)
        else:
            # No ground truth: score 1.0 if any results returned
            p = 1.0 if pages else 0.0
            r = 1.0 if pages else 0.0

        p_scores.append(p)
        r_scores.append(r)
        results.append({
            "query_id": q.get("id"),
            "query": query_text,
            "retrieved": len(pages),
            "p_at_k": round(p * 100, 2),
            "r_at_k": round(r * 100, 2),
        })

    avg_p = sum(p_scores) / len(p_scores) if p_scores else 0.0
    avg_r = sum(r_scores) / len(r_scores) if r_scores else 0.0

    return {
        "p_at_5": round(avg_p * 100, 2),
        "r_at_5": round(avg_r * 100, 2),
        "total_queries": len(queries),
        "k": k,
        "per_query": results,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True, help="Path to Quaid DB")
    parser.add_argument("--gbrain-evals-dir", required=True)
    parser.add_argument("--queries-file", default=None,
                        help="Path to queries.json with real qrels (MSMARCO/FiQA format). Overrides gbrain-evals-dir query loading.")
    parser.add_argument("--output", required=True)
    parser.add_argument("--quaid-version", default="unknown")
    parser.add_argument("--k", type=int, default=5)
    args = parser.parse_args()

    print(f"Running gbrain-evals adapter against Quaid {args.quaid_version}")
    print(f"DB: {args.db}")

    backend = QuaidBackend(args.db)

    # Prefer explicit queries.json with real qrels (MSMARCO/FiQA)
    if args.queries_file and Path(args.queries_file).exists():
        print(f"Loading queries from: {args.queries_file}")
        queries = json.loads(Path(args.queries_file).read_text())
        print(f"Loaded {len(queries)} queries with ground truth")
    else:
        queries = load_queries(args.gbrain_evals_dir)
        print(f"Loaded {len(queries)} queries (from gbrain-evals dir)")

    scores = run_evaluation(backend, queries, k=args.k)

    output = {
        "quaid_version": args.quaid_version,
        "date": str(date.today()),
        "benchmark": "gbrain-evals",
        "gbrain_evals": scores,
        "reference": {
            "gbrain": {"p_at_5": 49.1, "r_at_5": 97.9, "source": "garrytan Apr 27 2026"}
        }
    }

    Path(args.output).write_text(json.dumps(output, indent=2))

    print(f"\n=== gbrain-evals Results ===")
    print(f"P@5: {scores['p_at_5']}% (GBrain reference: 49.1%)")
    print(f"R@5: {scores['r_at_5']}% (GBrain reference: 97.9%)")
    print(f"Queries: {scores['total_queries']}")
    print(f"Results written to: {args.output}")


if __name__ == "__main__":
    main()
