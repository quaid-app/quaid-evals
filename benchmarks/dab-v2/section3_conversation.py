#!/usr/bin/env python3
"""
benchmarks/dab-v2/section3_conversation.py

§3 Conversation Memory (100pts)
Tests multi-session conversational recall.

For systems WITHOUT conversation memory (qmd, GBrain, Quaid pre-#105):
  All 4 subsections score 0/100.

For systems WITH conversation memory (Mem0, Quaid post-#105):
  Ingests 5 synthetic conversations, then runs recall queries.

Usage:
  python3 benchmarks/dab-v2/section3_conversation.py \
    --system quaid --db /path/to/db \
    --output results/s3-quaid-v0.11.6-2026-04-29.json
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path
from datetime import date


# ── Synthetic conversation corpus ─────────────────────────────────────────────
# 5 conversations covering the key test scenarios

CONVERSATIONS = [
    {
        "id": "conv-001",
        "turns": [
            {"role": "user", "content": "We need to decide on the benchmark corpus. I want to use something with real ground truth labels."},
            {"role": "assistant", "content": "Good call. Wikipedia has no qrels. FiQA has financial qrels. MSMARCO is the industry standard with 6,980 dev queries and human relevance judgments."},
            {"role": "user", "content": "Let's go with MSMARCO. Stream just 500 queries to keep the download small."},
            {"role": "assistant", "content": "Confirmed. We'll use MSMARCO dev subset, 500 queries, streaming via HuggingFace. ~50MB download instead of 2.9GB."},
            {"role": "user", "content": "Perfect. Also no em dashes in blog posts ever."},
            {"role": "assistant", "content": "Noted - no em dashes. Use hyphens or rewrite the sentence instead."},
        ]
    },
    {
        "id": "conv-002",
        "turns": [
            {"role": "user", "content": "What's the MCP config we need for Quaid in OpenClaw?"},
            {"role": "assistant", "content": "Add quaid under mcp.servers with command: quaid, args: [serve], and QUAID_DB env pointing to ~/.quaid/memory.db"},
            {"role": "user", "content": "And for the skill, Quaid memory_query should always run first before qmd."},
            {"role": "assistant", "content": "Right - memory_query first for semantic, memory_search for exact keywords, fall back to qmd only if Quaid returns empty."},
            {"role": "user", "content": "I prefer the bge-small model for now, not bge-base."},
            {"role": "assistant", "content": "bge-small it is. The comparison showed identical scores anyway - the §4 ceiling is corpus coverage, not model capacity."},
        ]
    },
    {
        "id": "conv-003",
        "turns": [
            {"role": "user", "content": "Who is Nicolò Boschi?"},
            {"role": "assistant", "content": "He's from Vectorize - they build Hindsight, which is SOTA on BEAM 10M. He replied to your tweet about Mem0's token efficiency."},
            {"role": "user", "content": "What did he say about Hindsight vs Mem0?"},
            {"role": "assistant", "content": "He said memory efficiency matters at scale, Mem0 works for simpler setups but Hindsight achieves SOTA on BEAM 10M where context stuffing is impossible."},
            {"role": "user", "content": "What question did I ask him that he hasn't answered yet?"},
            {"role": "assistant", "content": "You asked whether he's benchmarking against both BEAM tiers (100K and 10M) or mainly focused on the extreme scale. Still waiting on a reply as of April 29."},
        ]
    },
    {
        "id": "conv-004",
        "turns": [
            {"role": "user", "content": "What issues did we file for the Quaid roadmap?"},
            {"role": "assistant", "content": "Three key issues: #105 conversation turn ingestion (memory_add_turn), #106 native OpenClaw backend support, #107 zero-LLM entity extraction at write time."},
            {"role": "user", "content": "Which one is the most critical for Doug switching from qmd?"},
            {"role": "assistant", "content": "Issue #106 - the OpenClaw backend integration. Without it, Quaid isn't the active memory backend in sessions regardless of how good retrieval is."},
            {"role": "user", "content": "And what's the migration criteria?"},
            {"role": "assistant", "content": "DAB v2 total ≥ 300/400 across 2 consecutive releases. Currently at 87/400. Main gaps: conversation memory (0/100) and knowledge graph (5/80 estimated)."},
        ]
    },
    {
        "id": "conv-005",
        "turns": [
            {"role": "user", "content": "What was the CLARITY Act development today?"},
            {"role": "assistant", "content": "Senator Lummis confirmed Senate Banking Committee markup in May. This is the biggest legislative signal yet - markup means committee vote, which unlocks the floor path."},
            {"role": "user", "content": "And the Bitcoin reserve?"},
            {"role": "assistant", "content": "White House advisor said announcement is coming in weeks, not months. The BTC 2026 Conference in Las Vegas had FBI Director, SEC Chair, and CFTC Chair all speaking."},
            {"role": "user", "content": "What was the Coinbase CEO angle?"},
            {"role": "assistant", "content": "Brian Armstrong said stablecoins could slash $60 billion in annual remittance fees. Western Union launched their own stablecoin the same week."},
        ]
    }
]

# ── Test queries and expected answers ────────────────────────────────────────

S3_1_SINGLE_HOP = [
    ("What corpus did we decide to use for benchmarking?", ["MSMARCO", "msmarco"]),
    ("What is the rule about em dashes in blog posts?", ["no em dashes", "hyphen", "rewrite"]),
    ("What is the MCP command for Quaid in OpenClaw?", ["quaid serve", "quaid"]),
    ("Which embedding model did we choose to keep?", ["bge-small", "small"]),
    ("Who builds Hindsight?", ["Vectorize", "vectorize", "Nicolò", "Nicolo"]),
    ("What question did I ask Nicolò that hasn't been answered?", ["BEAM tiers", "both tiers", "extreme scale"]),
    ("What is issue #106 about?", ["OpenClaw backend", "native backend", "OpenClaw integration"]),
    ("What is the DAB v2 migration criteria?", ["300", "300/400"]),
    ("When is the CLARITY Act markup scheduled?", ["May", "next month"]),
    ("What did Brian Armstrong say about stablecoins and remittances?", ["60 billion", "$60B", "remittance fees"]),
]

S3_2_CROSS_SESSION = [
    ("What decisions have we made about the benchmark pipeline?", ["MSMARCO", "500 queries", "streaming"]),
    ("What is our overall strategy for Quaid vs qmd migration?", ["DAB v2", "300/400", "#106"]),
    ("What are the key crypto regulatory developments we've been tracking?", ["CLARITY Act", "Bitcoin reserve", "stablecoin"]),
    ("Who are the key people in the memory systems space we're engaging with?", ["Nicolò", "Vectorize", "Hindsight"]),
    ("What are the main gaps preventing Quaid from replacing qmd?", ["conversation memory", "#105", "#106"]),
]

S3_3_TEMPORAL = [
    ("What was the most recent decision we made?", ["DAB v2", "migration criteria", "300/400"]),
    ("What was the last crypto news item discussed?", ["stablecoin", "remittance", "Coinbase"]),
    ("What was the last question about Nicolò left unanswered?", ["BEAM tiers"]),
    ("What was the last development on CLARITY Act?", ["May markup", "Lummis"]),
    ("What was the most recent preference stated about embeddings?", ["bge-small"]),
]

S3_4_PREFERENCES = [
    ("What is the rule about em dashes?", ["no em dashes", "never", "hyphen"]),
    ("Which embedding model do I prefer?", ["bge-small", "small"]),
    ("In what order should memory tools be tried?", ["memory_query first", "qmd last", "fall back"]),
    ("How many MSMARCO queries should we stream?", ["500"]),
    ("What is the target DAB v2 score for migration?", ["300", "75%"]),
]


def ingest_conversations(system: str, db: str, conversations: list) -> bool:
    """Try to ingest conversations into the memory system."""
    if system == "quaid":
        # Try memory_add_turn via MCP if available, else skip
        try:
            test = subprocess.run(
                ["quaid", "memory_search", "test", "--db", db, "--limit", "1", "--json"],
                capture_output=True, text=True, timeout=10
            )
            if test.returncode != 0:
                return False
            
            # Write conversation turns as pages directly (pre-#105 workaround)
            import tempfile, os
            for conv in conversations:
                for i, turn in enumerate(conv["turns"]):
                    slug = f"conversations/{conv['id']}/turn-{i:03d}"
                    content = f"""---
session_id: "{conv['id']}"
turn_index: {i}
role: "{turn['role']}"
type: conversation_turn
---

**{turn['role'].capitalize()}:** {turn['content']}
"""
                    # Use quaid put
                    proc = subprocess.run(
                        ["quaid", "put", slug, "--db", db],
                        input=content, capture_output=True, text=True, timeout=10
                    )
            return True
        except Exception:
            return False
    
    elif system == "mem0":
        # Mem0 has native conversation ingestion via its Python API
        try:
            import mem0
            m = mem0.MemoryClient()
            for conv in conversations:
                messages = [{"role": t["role"], "content": t["content"]} for t in conv["turns"]]
                m.add(messages, user_id="dab-v2-test")
            return True
        except Exception:
            return False
    
    return False


def query_memory(system: str, db: str, query: str) -> str:
    """Query the memory system and return the top result text."""
    if system == "quaid":
        result = subprocess.run(
            ["quaid", "query", query, "--db", db, "--limit", "3", "--json"],
            capture_output=True, text=True, timeout=15
        )
        if result.returncode == 0 and result.stdout.strip():
            try:
                items = json.loads(result.stdout)
                return " ".join(x.get("summary", x.get("title", "")) for x in items[:3])
            except Exception:
                pass
    
    elif system == "mem0":
        try:
            import mem0
            m = mem0.MemoryClient()
            results = m.search(query, user_id="dab-v2-test", limit=3)
            return " ".join(r.get("memory", "") for r in results[:3])
        except Exception:
            pass
    
    return ""


def score_answer(response: str, keywords: list) -> bool:
    """Check if response contains any of the expected keywords."""
    resp_lower = response.lower()
    return any(kw.lower() in resp_lower for kw in keywords)


def run_s3(system: str, db: str) -> dict:
    """Run §3 conversation memory benchmark."""
    print(f"\n=== §3 Conversation Memory (100pts) ===")
    
    # Check if system supports conversation memory
    ingested = ingest_conversations(system, db, CONVERSATIONS)
    if not ingested:
        print(f"  {system} does not support conversation turn ingestion")
        print(f"  §3 Total: 0/100")
        return {
            "score": 0, "max": 100,
            "note": f"{system} does not support conversation memory (score 0 by design)",
            "breakdown": {"s3_1": 0, "s3_2": 0, "s3_3": 0, "s3_4": 0}
        }
    
    print(f"  Ingested {len(CONVERSATIONS)} conversations ({sum(len(c['turns']) for c in CONVERSATIONS)} turns)")
    
    # S3.1 Single-hop recall (30pts)
    s3_1_hits = 0
    for q, kws in S3_1_SINGLE_HOP:
        resp = query_memory(system, db, q)
        if score_answer(resp, kws):
            s3_1_hits += 1
    s3_1 = s3_1_hits * 3
    print(f"[S3.1] Single-hop: {s3_1_hits}/{len(S3_1_SINGLE_HOP)} → {s3_1}/30")
    
    # S3.2 Cross-session (30pts)
    s3_2_hits = 0
    for q, kws in S3_2_CROSS_SESSION:
        resp = query_memory(system, db, q)
        if score_answer(resp, kws):
            s3_2_hits += 1
    s3_2 = s3_2_hits * 6
    print(f"[S3.2] Cross-session: {s3_2_hits}/{len(S3_2_CROSS_SESSION)} → {s3_2}/30")
    
    # S3.3 Temporal (20pts)
    s3_3_hits = 0
    for q, kws in S3_3_TEMPORAL:
        resp = query_memory(system, db, q)
        if score_answer(resp, kws):
            s3_3_hits += 1
    s3_3 = s3_3_hits * 4
    print(f"[S3.3] Temporal: {s3_3_hits}/{len(S3_3_TEMPORAL)} → {s3_3}/20")
    
    # S3.4 Preferences (20pts)
    s3_4_hits = 0
    for q, kws in S3_4_PREFERENCES:
        resp = query_memory(system, db, q)
        if score_answer(resp, kws):
            s3_4_hits += 1
    s3_4 = s3_4_hits * 4
    print(f"[S3.4] Preferences: {s3_4_hits}/{len(S3_4_PREFERENCES)} → {s3_4}/20")
    
    total = s3_1 + s3_2 + s3_3 + s3_4
    print(f"§3 Total: {total}/100")
    
    return {
        "score": total, "max": 100,
        "breakdown": {"s3_1": s3_1, "s3_2": s3_2, "s3_3": s3_3, "s3_4": s3_4}
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--system", default="quaid")
    parser.add_argument("--db", default="/tmp/dab-v2-test.db")
    parser.add_argument("--output", default="results/s3-test.json")
    args = parser.parse_args()

    result = run_s3(args.system, args.db)
    result["system"] = args.system
    result["date"] = str(date.today())
    result["benchmark"] = "dab-v2-s3"
    
    Path(args.output).write_text(json.dumps(result, indent=2))
    print(f"\nResults: {args.output}")


if __name__ == "__main__":
    main()
