# LongMemEval Benchmark

Tests long-term memory across 500 questions and 6 question types. From ICLR 2025.

## What LongMemEval measures

| Question Type | Count | What it tests | Mem0 v3 |
|---------------|-------|--------------|---------|
| multi-session | 133 | Cross-session fact recall | ~93% |
| temporal-reasoning | 133 | Time-based reasoning ("Where did I live before SF?") | 93% |
| knowledge-update | 78 | Memory updates override stale facts | ~90% |
| single-session-user | 70 | User-stated facts in one session | ~95% |
| single-session-assistant | 56 | Assistant-generated facts (agent recall) | 100% |
| single-session-preference | 30 | User preferences stated in conversation | ~90% |
| **Overall** | **500** | | **93.4%** |

## Key difference from LoCoMo

Each question has its own **haystack sessions** (up to 53 sessions) that are ingested fresh per question. This isolates retrieval quality from cross-question memory pollution.

LoCoMo = shared corpus, all questions against same memory store.
LongMemEval = per-question corpus, truly isolated evaluation.

## Why Quaid scores will be low initially

Same gap as LoCoMo: Quaid stores raw conversation turns as documents, not extracted facts.
Retrieval from raw dialog cannot answer "What degree did I graduate with?" if the answer
is buried in a casual conversation.

**Issue #105** (conversation memory / fact extraction) closes this gap.

## Benchmark modes

### QA Accuracy (primary metric)

Measures end-to-end answer quality: does Quaid produce the correct answer string? This is the honest product metric - it exercises the full pipeline: ingest turns → retrieve → generate answer → judge.

**Current score (v0.20.0): 0.114 overall.** This reflects Quaid's actual capabilities today: turns are stored but the extraction worker requires `quaid serve` to be running (blocked by #177). Without extracted facts, retrieval returns raw turn text and answer quality is low.

```bash
# Full run (500 questions, ~2-3 hours)
OPENAI_API_KEY=sk-... bash benchmarks/longmemeval/run.sh

# Quick test (50 questions, ~15 mins)
MAX_QUESTIONS=50 OPENAI_API_KEY=sk-... bash benchmarks/longmemeval/run.sh
```

### Retrieval Recall R@5 (experimental, blocked)

Measures whether the right conversation session lands in the top-5 retrieved results. Same metric family as GBrain's 97.60% claim. **Currently returns 0.0** because:

1. The conversations collection isn't synced into the searchable index during benchmarks
2. `memory_query` doesn't expose source session provenance in result slugs

This mode will become meaningful when:
- **#177 ships** (HTTP daemon keeps extraction worker running during benchmarks)
- Extracted fact pages carry session provenance back to `answer_session_ids`

Do not use R@5 for product comparisons until the pipeline is end-to-end functional.

```bash
# Recall mode - currently experimental/blocked
METRIC=recall bash benchmarks/longmemeval/run.sh
```

## Why QA accuracy is the honest metric

Building a purpose-built retrieval adapter (index sessions as flat documents, query session IDs) would produce a higher R@5 but would bypass the actual `memory_add_turn → extraction → memory_query` pipeline that real users interact with. That's benchmark theater.

The 0.114 QA accuracy score is what Quaid does today. As #177 ships and extraction runs continuously, that number should improve naturally - no special adapters needed.
