# gbrain-evals Adapter

Runs [Garry Tan's gbrain-evals](https://github.com/garrytan/gbrain-evals) eval harness against Quaid.

## Metrics

- **P@5** (Precision at 5): Of 5 results returned, how many are relevant? GBrain reference: **49.1%**
- **R@5** (Recall at 5): Of all relevant pages, how many appear in top 5? GBrain reference: **97.9%**

## How it works

1. Clones `garrytan/gbrain-evals`
2. Indexes the qrels corpus from `scripts/setup-corpus.sh` into a fresh Quaid DB
3. Runs 500 queries with human relevance labels via the Quaid CLI adapter
4. Computes P@5 and R@5 from passage IDs or relevant file paths
5. Outputs JSON with per-query breakdown + summary

## Running

```bash
bash benchmarks/gbrain-evals/run.sh
```

Output: `results/gbrain-evals-<version>-<date>.json`

## Notes

- Queries without ground-truth labels now fail the run instead of falling back to result-count scoring.
- The corpus used here is MSMARCO when HuggingFace streaming succeeds, or the FiQA fallback corpus otherwise. Scores are not directly comparable to GBrain's published corpus, but they are grounded in real qrels.
