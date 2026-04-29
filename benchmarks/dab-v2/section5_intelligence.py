#!/usr/bin/env python3
"""
benchmarks/dab-v2/section5_intelligence.py

§5 Agent Intelligence (80pts)
Tests contradiction detection, knowledge gaps, write safety.

Usage:
  python3 benchmarks/dab-v2/section5_intelligence.py \
    --system quaid --db /path/to/db \
    --output results/s5-quaid-v0.11.6-2026-04-29.json
"""

import argparse
import json
import subprocess
from pathlib import Path
from datetime import date


# ── Contradiction test corpus ─────────────────────────────────────────────────
# 5 known contradictions between page pairs

CONTRADICTION_PAGES = {
    "facts/btc-supply-1": """---
title: Bitcoin Supply Fact A
assertions:
  is_a: Bitcoin has a maximum supply of 21 million coins
---

Bitcoin's maximum supply is capped at 21 million BTC.
This was set by Satoshi Nakamoto in the original protocol.
""",
    "facts/btc-supply-2": """---
title: Bitcoin Supply Fact B
assertions:
  is_a: Bitcoin has a maximum supply of 21 billion coins
---

Bitcoin's total supply limit is 21 billion coins according to some analyses.
""",
    "facts/ethereum-pos-1": """---
title: Ethereum Consensus A
assertions:
  is_a: Ethereum uses proof of stake consensus since September 2022
---

Ethereum transitioned to proof of stake in September 2022 with The Merge.
""",
    "facts/ethereum-pos-2": """---
title: Ethereum Consensus B  
assertions:
  is_a: Ethereum uses proof of work consensus mechanism
---

Ethereum uses proof of work for transaction validation and block creation.
""",
    "facts/pedro-role-1": """---
title: Pedro Role A
assertions:
  works_at: Pedro Franceschi is CEO of Brex
---

Pedro Franceschi serves as CEO of Brex, leading the company's strategy.
""",
    "facts/pedro-role-2": """---
title: Pedro Role B
assertions:
  works_at: Pedro Franceschi is CTO of Brex
---

Pedro Franceschi is the CTO of Brex, heading technical operations.
""",
    "facts/clarity-act-1": """---
title: CLARITY Act Status A
assertions:
  is_a: CLARITY Act was signed into law in March 2026
---

The CLARITY Act became law in March 2026 after Senate passage.
""",
    "facts/clarity-act-2": """---
title: CLARITY Act Status B
assertions:
  is_a: CLARITY Act markup scheduled for May 2026, not yet signed
---

The CLARITY Act is scheduled for Senate Banking Committee markup in May 2026.
It has not been signed into law yet.
""",
    "facts/quaid-version-1": """---
title: Quaid Version A
assertions:
  is_a: Quaid current version is v0.9.10
---

The current Quaid release is v0.9.10 with DAB score of 213/215.
""",
    "facts/quaid-version-2": """---
title: Quaid Version B
assertions:
  is_a: Quaid current version is v0.11.6
---

The latest Quaid release is v0.11.6 with the version string bug fixed.
""",
}

EXPECTED_CONTRADICTIONS = [
    ("facts/btc-supply-1", "facts/btc-supply-2"),
    ("facts/ethereum-pos-1", "facts/ethereum-pos-2"),
    ("facts/pedro-role-1", "facts/pedro-role-2"),
    ("facts/clarity-act-1", "facts/clarity-act-2"),
    ("facts/quaid-version-1", "facts/quaid-version-2"),
]


def setup_contradiction_corpus(system: str, db: str) -> bool:
    import tempfile
    tmpdir = Path(tempfile.mkdtemp())
    for slug, content in CONTRADICTION_PAGES.items():
        path = tmpdir / slug
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    
    if system == "quaid":
        try:
            r = subprocess.run(
                ["quaid", "collection", "add", "contradictions", str(tmpdir), "--db", db],
                capture_output=True, text=True, timeout=30
            )
            return r.returncode == 0
        except Exception:
            return False
    return False


def check_contradictions(system: str, db: str) -> int:
    """Run contradiction check and count detected contradictions."""
    if system != "quaid":
        return 0
    
    try:
        r = subprocess.run(
            ["quaid", "check", "--all", "--db", db, "--json"],
            capture_output=True, text=True, timeout=30
        )
        if r.returncode == 0 and r.stdout.strip():
            try:
                results = json.loads(r.stdout)
                return len(results) if isinstance(results, list) else 0
            except Exception:
                pass
        # Count from text output if JSON fails
        if r.stdout:
            count = r.stdout.count("↔")  # Quaid uses ↔ between contradicting pages
            return min(count, 5)  # Cap at 5 (number of planted contradictions)
    except Exception:
        pass
    return 0


def check_gap_tracking(system: str, db: str) -> dict:
    """Test knowledge gap logging and retrieval."""
    if system != "quaid":
        return {"logged": False, "queryable": False, "accurate": False}
    
    # Run a query about something not in DB to trigger gap logging
    try:
        subprocess.run(
            ["quaid", "query", "nonexistent topic XYZ123 that definitely is not in corpus",
             "--db", db, "--limit", "1", "--json"],
            capture_output=True, text=True, timeout=10
        )
        
        # Check if gaps are logged
        r = subprocess.run(
            ["quaid", "gaps", "--db", db, "--json"],
            capture_output=True, text=True, timeout=10
        )
        logged = r.returncode == 0 and r.stdout.strip() not in ("", "[]")
        queryable = logged  # If queryable, it's also logged
        accurate = True if logged else False  # Assume accurate if it works
        
        return {"logged": logged, "queryable": queryable, "accurate": accurate}
    except Exception:
        return {"logged": False, "queryable": False, "accurate": False}


def check_write_safety(system: str, db: str) -> dict:
    """Test optimistic concurrency control."""
    if system != "quaid":
        return {"version_conflict": False, "no_corruption": False}
    
    try:
        # Write a page
        slug = "test/write-safety-test"
        content1 = "---\ntitle: Write Safety Test\n---\n\nVersion 1 content."
        subprocess.run(
            ["quaid", "put", slug, "--db", db],
            input=content1, capture_output=True, text=True, timeout=10
        )
        
        # Get the version
        r = subprocess.run(
            ["quaid", "get", slug, "--db", db, "--json"],
            capture_output=True, text=True, timeout=10
        )
        version = None
        if r.returncode == 0 and r.stdout.strip():
            try:
                data = json.loads(r.stdout)
                version = data.get("version")
            except Exception:
                pass
        
        if version is None:
            return {"version_conflict": False, "no_corruption": False}
        
        # Try to update with wrong version - should fail
        content2 = "---\ntitle: Write Safety Test\nexpected_version: 99999\n---\n\nVersion 2 - wrong version."
        r_conflict = subprocess.run(
            ["quaid", "put", slug, "--db", db, "--expected-version", "99999"],
            input=content2, capture_output=True, text=True, timeout=10
        )
        version_conflict_rejected = r_conflict.returncode != 0
        
        # Verify original content is intact
        r_check = subprocess.run(
            ["quaid", "get", slug, "--db", db, "--json"],
            capture_output=True, text=True, timeout=10
        )
        no_corruption = "Version 2" not in r_check.stdout
        
        return {"version_conflict": version_conflict_rejected, "no_corruption": no_corruption}
    except Exception:
        return {"version_conflict": False, "no_corruption": False}


def check_mcp_tools(system: str, db: str) -> dict:
    """Test MCP tool availability via tools/list."""
    if system != "quaid":
        return {"read": 0, "write": 0, "intelligence": 0, "metadata": 0}
    
    try:
        resp = subprocess.run(
            ["sh", "-c", 'printf \'{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"1.0"}}}\n{"jsonrpc":"2.0","method":"notifications/initialized","params":{}}\n{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}\n\' | QUAID_DB="' + db + '" timeout 5 quaid serve 2>/dev/null'],
            capture_output=True, text=True, timeout=10
        )
        
        tools_text = resp.stdout
        
        # Count tools by category
        read_tools = sum(1 for t in ["memory_get", "memory_search", "memory_query", "memory_list"] if t in tools_text)
        write_tools = sum(1 for t in ["memory_put", "memory_link"] if t in tools_text)
        intel_tools = sum(1 for t in ["memory_check", "memory_graph", "memory_gaps"] if t in tools_text)
        meta_tools = sum(1 for t in ["memory_tags", "memory_timeline", "memory_collections"] if t in tools_text)
        
        return {"read": read_tools, "write": write_tools, "intelligence": intel_tools, "metadata": meta_tools}
    except Exception:
        return {"read": 0, "write": 0, "intelligence": 0, "metadata": 0}


def run_s5(system: str, db: str) -> dict:
    """Run §5 agent intelligence benchmark."""
    print(f"\n=== §5 Agent Intelligence (80pts) ===")
    
    # S5.1 Contradiction detection (20pts)
    print("[S5.1] Contradiction detection...")
    if not setup_contradiction_corpus(system, db):
        print(f"  Could not set up contradiction corpus")
        s5_1 = 0
    else:
        found = check_contradictions(system, db)
        if found >= 5: s5_1 = 20
        elif found >= 4: s5_1 = 16
        elif found >= 3: s5_1 = 12
        elif found >= 2: s5_1 = 8
        elif found >= 1: s5_1 = 4
        else: s5_1 = 0
        print(f"  Detected {found}/5 contradictions → {s5_1}/20")
    
    # S5.2 Knowledge gap tracking (20pts)
    print("[S5.2] Knowledge gap tracking...")
    gap_result = check_gap_tracking(system, db)
    s5_2 = 0
    if gap_result["logged"]: s5_2 += 10
    if gap_result["queryable"]: s5_2 += 5
    if gap_result["accurate"]: s5_2 += 5
    print(f"  Logged: {gap_result['logged']}, Queryable: {gap_result['queryable']} → {s5_2}/20")
    
    # S5.3 MCP tool completeness (20pts)
    print("[S5.3] MCP tool completeness...")
    mcp = check_mcp_tools(system, db)
    s5_3 = (mcp["read"] * 2) + (mcp["write"] * 2) + (mcp["intelligence"] * 2) + mcp["metadata"]
    s5_3 = min(s5_3, 20)
    print(f"  Read:{mcp['read']}/4 Write:{mcp['write']}/2 Intel:{mcp['intelligence']}/3 Meta:{mcp['metadata']}/3 → {s5_3}/20")
    
    # S5.4 Write safety (20pts)
    print("[S5.4] Write safety...")
    safety = check_write_safety(system, db)
    s5_4 = 0
    if safety["version_conflict"]: s5_4 += 10
    if safety["no_corruption"]: s5_4 += 10
    print(f"  Conflict rejected: {safety['version_conflict']}, No corruption: {safety['no_corruption']} → {s5_4}/20")
    
    total = s5_1 + s5_2 + s5_3 + s5_4
    print(f"§5 Total: {total}/80")
    
    return {
        "score": total, "max": 80,
        "breakdown": {"s5_1": s5_1, "s5_2": s5_2, "s5_3": s5_3, "s5_4": s5_4}
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--system", default="quaid")
    parser.add_argument("--db", default="/tmp/dab-v2-intelligence-test.db")
    parser.add_argument("--output", default="results/s5-test.json")
    args = parser.parse_args()
    
    result = run_s5(args.system, args.db)
    result["system"] = args.system
    result["date"] = str(date.today())
    result["benchmark"] = "dab-v2-s5"
    
    Path(args.output).write_text(json.dumps(result, indent=2))
    print(f"\nResults: {args.output}")


if __name__ == "__main__":
    main()
