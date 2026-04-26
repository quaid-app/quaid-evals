# DAB - Doug Aillm Benchmark

Tests Quaid's retrieval quality across 8 dimensions on a 350-page PARA corpus.

## Scoring (215 pts max)

| Section | Points | What's tested |
|---------|--------|---------------|
| Install | 10 | Binary installs, version reports |
| Collection add | 30 | Corpus ingestion speed and completeness |
| FTS | 40 | Full-text search recall (5 queries) |
| Semantic | 50 | Vector/hybrid semantic search (6 queries) |
| Performance | 30 | Latency thresholds (FTS <100ms, semantic <500ms, add <10s) |
| Integrity | 20 | All pages indexed and retrievable |
| Collections | 15 | Collection management API works |
| MCP | 20 | MCP server starts and responds |

## Running

```bash
bash benchmarks/dab/run.sh
```

Output: `results/dab-<version>-<date>.json`
