# gbrain-evals Adapter

Runs [Garry Tan's gbrain-evals](https://github.com/garrytan/gbrain-evals) eval harness against Quaid.

## Metrics

- **P@5** (Precision at 5): Of 5 results returned, how many are relevant? GBrain reference: **49.1%**
- **R@5** (Recall at 5): Of all relevant pages, how many appear in top 5? GBrain reference: **97.9%**

## How it works

1. Clones `garrytan/gbrain-evals`
2. Indexes the DAB corpus into a fresh Quaid DB
3. Runs the 145 eval queries via `QuaidBackend` adapter (`quaid memory_query --json`)
4. Computes P@5 and R@5
5. Outputs JSON with per-query breakdown + summary

## Running

```bash
bash benchmarks/gbrain-evals/run.sh
```

Output: `results/gbrain-evals-<version>-<date>.json`

## Notes

- When gbrain-evals has no ground-truth relevance labels for a query, falls back to binary (results returned = pass)
- The corpus used here (350 PARA pages) differs from GBrain's corpus (17,888 wiki pages) - scores are not directly comparable but show relative trends
