#!/usr/bin/env python3
"""
generate-corpus.py - Generate a synthetic PARA-structured markdown corpus for benchmarks.
Used when the official DAB corpus is not available (e.g., in CI without access).
"""
import os
import sys
import json
import random
import argparse
from pathlib import Path

PARA_STRUCTURE = {
    "1. Projects": ["project-alpha", "project-beta", "project-gamma"],
    "2. Areas": ["engineering", "finance", "health", "learning"],
    "3. Resources": ["AI-Tools", "Finance", "Dev-Tools", "Research"],
    "4. Archives": ["2024", "2025"],
}

TOPICS = [
    ("agent memory architecture", "Memory systems for AI agents require persistent storage across sessions."),
    ("DeFi liquidity protocols", "Automated market makers rely on liquidity pools to enable token swaps."),
    ("Rust performance tuning", "Zero-cost abstractions in Rust enable systems-level performance."),
    ("PARA method organization", "Projects, Areas, Resources, Archives form a complete knowledge system."),
    ("stablecoin regulation", "Regulatory clarity on stablecoins impacts institutional adoption."),
    ("vector embeddings", "Semantic search via dense vector representations enables fuzzy matching."),
    ("graph databases", "Graph structures model entity relationships more naturally than tables."),
    ("token economics", "Token supply, velocity, and utility drive long-term value accrual."),
    ("smart contract auditing", "Formal verification reduces exploit surface in DeFi protocols."),
    ("retrieval-augmented generation", "RAG combines document retrieval with generative models for grounded answers."),
]


def generate_page(title: str, content: str, tags: list[str]) -> str:
    return f"""---
title: "{title}"
tags: {json.dumps(tags)}
date: 2025-{random.randint(1,12):02d}-{random.randint(1,28):02d}
---

# {title}

{content}

## Key Points

{"".join(f"- {t[0].capitalize()}: {t[1][:60]}...{chr(10)}" for t in random.sample(TOPICS, 3))}

## Notes

This document covers {title.lower()} in the context of modern software and finance.
Related topics include {", ".join(random.choice(TOPICS)[0] for _ in range(3))}.
"""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--pages", type=int, default=350)
    args = parser.parse_args()

    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)

    pages_per_folder = args.pages // sum(len(v) for v in PARA_STRUCTURE.values())
    count = 0

    for folder, subfolders in PARA_STRUCTURE.items():
        for subfolder in subfolders:
            path = out / folder / subfolder
            path.mkdir(parents=True, exist_ok=True)
            for i in range(max(1, pages_per_folder)):
                topic = random.choice(TOPICS)
                title = f"{topic[0].title()} - Part {i+1}"
                tags = [topic[0].split()[0], subfolder, folder.split(". ")[1].lower()]
                page = generate_page(title, topic[1], tags)
                (path / f"page-{count:04d}.md").write_text(page)
                count += 1

    print(f"Generated {count} pages in {out}")


if __name__ == "__main__":
    main()
