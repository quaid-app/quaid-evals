# BEAM Benchmark

Tests Quaid at extreme memory scale: 100K, 1M, and 10M token corpora.

BEAM is Mem0's open-source benchmark where context stuffing is physically impossible.

## Reference scores

| System | BEAM 1M | BEAM 10M |
|--------|---------|---------|
| Mem0 v3 | 64.1% | 48.6% |
| Hindsight | TBD | SOTA |
| Quaid | TBD | TBD |

## Status

BEAM requires an LLM judge (OpenAI API) for scoring. Set `OPENAI_API_KEY` in CI secrets.

GitHub Actions runs a small smoke slice by default because the current adapter uses a fresh Quaid DB and embedding pass per conversation. Use `MAX_CONVERSATIONS=all` when you explicitly want the full split.

## Running

```bash
OPENAI_API_KEY=sk-... bash benchmarks/beam/run.sh
MAX_CONVERSATIONS=all OPENAI_API_KEY=sk-... bash benchmarks/beam/run.sh
```
