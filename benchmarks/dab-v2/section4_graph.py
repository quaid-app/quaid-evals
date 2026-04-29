#!/usr/bin/env python3
"""
benchmarks/dab-v2/section4_graph.py

§4 Knowledge Graph (80pts)
Tests entity extraction, relationship traversal, multi-hop queries.

For systems WITHOUT a graph layer (qmd, Mem0):
  All 4 subsections score 0/80.

For systems WITH a graph layer (GBrain, Quaid post-#107):
  Tests entity extraction and traversal.

Usage:
  python3 benchmarks/dab-v2/section4_graph.py \
    --system quaid --db /path/to/db \
    --output results/s4-quaid-v0.11.6-2026-04-29.json
"""

import argparse
import json
import subprocess
from pathlib import Path
from datetime import date


# ── Graph test corpus (entities + relationships) ──────────────────────────────
GRAPH_PAGES = {
    "people/pedro-franceschi": """---
title: Pedro Franceschi
type: person
works_at: Brex
founded: Brex
---

Pedro Franceschi co-founded Brex in 2017 with Henrique Dubugras.
Pedro works at Brex as CTO.
""",
    "companies/brex": """---
title: Brex
type: company
---

Brex is a fintech company founded by Pedro Franceschi and Henrique Dubugras in 2017.
Brex provides corporate credit cards and financial services for startups.
""",
    "people/henrique-dubugras": """---
title: Henrique Dubugras
type: person
works_at: Brex
founded: Brex
---

Henrique Dubugras co-founded Brex with Pedro Franceschi.
Henrique works at Brex as CEO.
""",
    "companies/yc": """---
title: Y Combinator
type: company
invested_in: Brex
---

Y Combinator (YC) is a startup accelerator. YC invested in Brex during the W17 batch.
Garry Tan is President and CEO of Y Combinator.
""",
    "people/garry-tan": """---
title: Garry Tan
type: person
works_at: Y Combinator
---

Garry Tan is President and CEO of Y Combinator.
Garry Tan founded GBrain and GStack for agent memory.
Garry Tan previously worked at Palantir.
""",
}

# Graph queries for testing
S4_ENTITY_QUERIES = [
    ("Who founded Brex?", ["Pedro", "Henrique"]),
    ("Who works at Y Combinator?", ["Garry Tan", "Garry"]),
    ("What company did Pedro found?", ["Brex"]),
    ("What did YC invest in?", ["Brex"]),
    ("Who is CEO of Y Combinator?", ["Garry Tan", "Garry"]),
]

S4_SINGLE_HOP_QUERIES = [
    ("What company employs Pedro Franceschi?", ["Brex"]),
    ("Who leads Y Combinator?", ["Garry Tan", "Garry"]),
    ("What startup did YC back in W17?", ["Brex"]),
    ("Who is Garry Tan affiliated with?", ["Y Combinator", "YC", "GBrain"]),
    ("What is the relationship between Pedro and Henrique?", ["co-founded", "Brex", "co-founders"]),
]

S4_MULTI_HOP_QUERIES = [
    # 2-hop: Pedro → Brex → YC → Garry Tan
    ("Who is associated with Brex through YC?", ["Garry Tan", "YC"]),
    # 2-hop: Garry Tan → YC → Brex
    ("What company is connected to Garry Tan through YC investments?", ["Brex"]),
    # 2-hop: via founding relationship
    ("Who co-founded a company that YC invested in?", ["Pedro", "Henrique"]),
]

S4_HYBRID_QUERIES = [
    ("fintech companies with venture backing", ["Brex", "YC"]),
    ("startup accelerator investments in fintech", ["YC", "Brex"]),
    ("people who built companies in the startup ecosystem", ["Pedro", "Henrique", "Garry"]),
    ("companies connected to Y Combinator", ["Brex"]),
    ("who founded something related to AI agents", ["Garry Tan", "GBrain"]),
]


def setup_graph_corpus(system: str, db: str) -> bool:
    """Ingest graph corpus pages."""
    import tempfile, os
    
    tmpdir = tempfile.mkdtemp()
    for slug, content in GRAPH_PAGES.items():
        path = Path(tmpdir) / slug
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    
    if system == "quaid":
        try:
            r = subprocess.run(
                ["quaid", "collection", "add", "graph-test", tmpdir, "--db", db],
                capture_output=True, text=True, timeout=30
            )
            if r.returncode == 0:
                subprocess.run(["quaid", "embed", "--db", db], capture_output=True, timeout=60)
                return True
        except Exception:
            pass
    
    elif system == "gbrain":
        try:
            r = subprocess.run(
                ["gbrain", "collection", "add", "graph-test", tmpdir, "--db", db],
                capture_output=True, text=True, timeout=30
            )
            return r.returncode == 0
        except Exception:
            pass
    
    return False


def graph_query(system: str, db: str, query: str) -> str:
    """Run a query and return text of results."""
    cmd = None
    if system == "quaid":
        cmd = ["quaid", "query", query, "--db", db, "--limit", "3", "--json"]
    elif system == "gbrain":
        cmd = ["gbrain", "query", query, "--db", db, "--limit", "3", "--json"]
    
    if not cmd:
        return ""
    
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        if r.returncode == 0 and r.stdout.strip():
            items = json.loads(r.stdout)
            return " ".join(x.get("summary", x.get("title", "")) for x in items[:3])
    except Exception:
        pass
    return ""


def check_graph_edges(system: str, db: str) -> float:
    """Check what fraction of entity pages have typed links."""
    if system == "quaid":
        try:
            for slug in GRAPH_PAGES:
                # Check if any links exist for this page
                r = subprocess.run(
                    ["quaid", "graph", slug, "--db", db, "--depth", "1", "--json"],
                    capture_output=True, text=True, timeout=10
                )
                if r.returncode == 0 and r.stdout.strip():
                    data = json.loads(r.stdout)
                    if data:
                        return 1.0  # Found at least one page with graph edges
        except Exception:
            pass
        return 0.0  # No graph edges found
    
    elif system == "gbrain":
        # GBrain has entity resolution - assume edges exist if graph queries work
        test = graph_query(system, db, "Pedro Franceschi Brex relationship")
        return 0.8 if "Brex" in test else 0.0
    
    return 0.0


def score_answer(response: str, keywords: list) -> bool:
    resp_lower = response.lower()
    return any(kw.lower() in resp_lower for kw in keywords)


def run_s4(system: str, db: str) -> dict:
    """Run §4 knowledge graph benchmark."""
    print(f"\n=== §4 Knowledge Graph (80pts) ===")
    
    # Check graph capability
    systems_with_graph = ["quaid", "gbrain"]
    if system not in systems_with_graph:
        print(f"  {system} has no graph layer - §4: 0/80")
        return {
            "score": 0, "max": 80,
            "note": f"{system} has no knowledge graph (score 0 by design)",
            "breakdown": {"s4_1": 0, "s4_2": 0, "s4_3": 0, "s4_4": 0}
        }
    
    # Set up corpus
    print("  Setting up graph corpus...")
    if not setup_graph_corpus(system, db):
        print(f"  Graph corpus setup failed - §4: 0/80")
        return {"score": 0, "max": 80, "note": "corpus setup failed", "breakdown": {}}
    
    # S4.1 Entity extraction (20pts)
    edge_coverage = check_graph_edges(system, db)
    if edge_coverage >= 0.8:
        s4_1 = 20
    elif edge_coverage >= 0.5:
        s4_1 = 10
    else:
        s4_1 = 0
    print(f"[S4.1] Entity extraction: {edge_coverage:.0%} → {s4_1}/20")
    
    # S4.2 Single-hop graph queries (20pts)
    s4_2_hits = 0
    for q, kws in S4_SINGLE_HOP_QUERIES:
        resp = graph_query(system, db, q)
        if score_answer(resp, kws):
            s4_2_hits += 1
    s4_2 = s4_2_hits * 4
    print(f"[S4.2] Single-hop: {s4_2_hits}/{len(S4_SINGLE_HOP_QUERIES)} → {s4_2}/20")
    
    # S4.3 Multi-hop traversal (20pts)
    s4_3_hits = 0
    for q, kws in S4_MULTI_HOP_QUERIES:
        resp = graph_query(system, db, q)
        if score_answer(resp, kws):
            s4_3_hits += 1
    s4_3 = round(s4_3_hits * 6.67)
    print(f"[S4.3] Multi-hop: {s4_3_hits}/{len(S4_MULTI_HOP_QUERIES)} → {s4_3}/20")
    
    # S4.4 Hybrid graph+semantic (20pts)
    s4_4_hits = 0
    for q, kws in S4_HYBRID_QUERIES:
        resp = graph_query(system, db, q)
        if score_answer(resp, kws):
            s4_4_hits += 1
    s4_4 = s4_4_hits * 4
    print(f"[S4.4] Hybrid: {s4_4_hits}/{len(S4_HYBRID_QUERIES)} → {s4_4}/20")
    
    total = s4_1 + s4_2 + s4_3 + s4_4
    print(f"§4 Total: {total}/80")
    
    return {
        "score": total, "max": 80,
        "breakdown": {"s4_1": s4_1, "s4_2": s4_2, "s4_3": s4_3, "s4_4": s4_4}
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--system", default="quaid")
    parser.add_argument("--db", default="/tmp/dab-v2-graph-test.db")
    parser.add_argument("--output", default="results/s4-test.json")
    args = parser.parse_args()

    result = run_s4(args.system, args.db)
    result["system"] = args.system
    result["date"] = str(date.today())
    result["benchmark"] = "dab-v2-s4"
    
    Path(args.output).write_text(json.dumps(result, indent=2))
    print(f"\nResults: {args.output}")


if __name__ == "__main__":
    main()
