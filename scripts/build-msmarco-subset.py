#!/usr/bin/env python3
"""
build-msmarco-subset.py - Stream MSMARCO dev subset from HuggingFace.

Pulls only what's needed for benchmarking - no 2.9GB full download:
  - Streams microsoft/ms_marco v1.1 validation split
  - Takes first 500 queries with at least 1 relevant passage
  - Writes passage files + queries.json + qrels.json

Total download: ~50-80MB (vs 2.9GB for full collection).
Works in GitHub Actions. Local sandbox may block HuggingFace Hub.

Output directory: CORPUS_DIR (default /tmp/quaid-bench-corpus)
"""

import json
import os
import re
import sys
from pathlib import Path
from collections import defaultdict

CORPUS_DIR = Path(os.environ.get("CORPUS_DIR", "/tmp/quaid-bench-corpus"))
MAX_QUERIES = 500

CORPUS_DIR.mkdir(parents=True, exist_ok=True)

# Check if already built
existing_queries = CORPUS_DIR / "queries.json"
if existing_queries.exists():
    try:
        qs = json.loads(existing_queries.read_text())
        if len(qs) >= MAX_QUERIES:
            print(f"Corpus already built ({len(qs)} queries). Skipping.")
            sys.exit(0)
    except Exception:
        pass

print("Building MSMARCO corpus via HuggingFace streaming...")
print(f"Output: {CORPUS_DIR}")
print(f"Target: {MAX_QUERIES} queries with ground truth")

try:
    from datasets import load_dataset
except ImportError:
    print("Installing datasets library...")
    import subprocess
    subprocess.run([sys.executable, "-m", "pip", "install", "datasets", "-q"], check=True)
    from datasets import load_dataset

# Stream validation split - no full download
print("Streaming microsoft/ms_marco v1.1 validation split...")
ds = load_dataset("microsoft/ms_marco", "v1.1", split="validation", streaming=True)

# PARA-like topic clustering
CLUSTERS = {
    "1. Projects/factual-qa":    ["what is", "what are", "define", "what does", "what was", "what were"],
    "1. Projects/how-to":        ["how to", "how do", "how can", "how does", "how did", "steps to"],
    "2. Areas/science-tech":     ["computer", "software", "algorithm", "data", "technology", "internet", "network"],
    "2. Areas/health-medicine":  ["health", "medical", "disease", "symptom", "treatment", "body", "doctor"],
    "3. Resources/history":      ["history", "when did", "who was", "who were", "founded", "invented", "origin"],
    "3. Resources/reference":    ["how many", "how much", "how long", "how far", "distance", "cost", "price", "average"],
    "4. Archives/other":         [],
}

def cluster_for(query):
    q = query.lower()
    for folder, kws in CLUSTERS.items():
        if any(k in q for k in kws):
            return folder
    return "4. Archives/other"

queries = {}
qrels = {}
all_passages = {}   # pid -> text
passage_to_file = {}

print(f"Processing stream (stopping at {MAX_QUERIES} valid queries)...")

for item in ds:
    if len(queries) >= MAX_QUERIES:
        break

    qid = str(item["query_id"])
    query_text = item["query"]
    passage_texts = item["passages"]["passage_text"]
    is_selected   = item["passages"]["is_selected"]
    urls          = item["passages"]["url"]

    relevant_pids = []
    item_passages = {}
    for j, (ptext, sel, url) in enumerate(zip(passage_texts, is_selected, urls)):
        pid = f"{qid}_{j}"
        item_passages[pid] = {"text": ptext, "url": url}
        if sel:
            relevant_pids.append(pid)

    if not relevant_pids:
        continue  # skip queries with no ground truth

    queries[qid] = query_text
    qrels[qid] = relevant_pids
    all_passages.update(item_passages)

    if len(queries) % 50 == 0:
        print(f"  {len(queries)}/{MAX_QUERIES} queries collected...")

print(f"Collected {len(queries)} queries, {len(all_passages):,} passages")

# Write passage files
print("Writing passage files...")
for qid, query_text in queries.items():
    cluster = cluster_for(query_text)
    folder = CORPUS_DIR / "passages" / cluster
    folder.mkdir(parents=True, exist_ok=True)

    pids = [pid for pid in all_passages if pid.startswith(f"{qid}_")]
    for pid in pids:
        pdata = all_passages[pid]
        is_rel = pid in qrels.get(qid, [])
        slug = re.sub(r"[^\w]", "-", pid)[:60]
        filepath = folder / f"{slug}.md"
        filepath.write_text(f"""---
passage_id: "{pid}"
query_id: "{qid}"
is_relevant: {str(is_rel).lower()}
source_url: "{pdata['url']}"
---

{pdata['text']}
""")
        passage_to_file[pid] = str(filepath.relative_to(CORPUS_DIR / "passages"))

total_written = len(passage_to_file)
print(f"Written {total_written:,} passage files")

# queries.json - gbrain-evals compatible format
queries_out = [
    {
        "id": qid,
        "query": queries[qid],
        "relevant_ids": qrels[qid],
        "relevant_files": [passage_to_file.get(p, "") for p in qrels[qid]],
    }
    for qid in queries
]
(CORPUS_DIR / "queries.json").write_text(json.dumps(queries_out, indent=2))

# qrels.json
(CORPUS_DIR / "qrels.json").write_text(json.dumps(
    {qid: qrels[qid] for qid in queries}, indent=2
))

print(f"\n=== MSMARCO Corpus Ready ===")
print(f"Queries:    {len(queries_out)}")
print(f"Passages:   {total_written:,}")
total_rel = sum(len(v) for v in qrels.values())
print(f"Qrels:      {total_rel} relevant pairs")
print(f"Avg rel/q:  {total_rel/len(queries):.1f}")
print(f"Location:   {CORPUS_DIR}")
