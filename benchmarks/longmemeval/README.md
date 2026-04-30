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

## Running

```bash
# Full run (500 questions, ~2-3 hours at 30K TPM)
OPENAI_API_KEY=sk-... bash benchmarks/longmemeval/run.sh

# Faster test (50 questions, ~15 mins)
MAX_QUESTIONS=50 OPENAI_API_KEY=sk-... bash benchmarks/longmemeval/run.sh

# Anthropic provider
LLM_PROVIDER=anthropic ANSWERER_MODEL=claude-3-5-haiku-20241022 JUDGE_MODEL=claude-3-5-haiku-20241022 bash benchmarks/longmemeval/run.sh
```

Output: `results/longmemeval-<version>-<date>.json`
