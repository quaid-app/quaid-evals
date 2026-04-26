#!/usr/bin/env bash
# benchmarks/gbrain-evals/run.sh - Run Garry Tan's gbrain-evals against Quaid
# Outputs: results/gbrain-evals-<version>-<date>.json

set -euo pipefail

QUAID_VERSION=$(quaid --version 2>/dev/null | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1 || echo "unknown")
DATE=$(date +%Y-%m-%d)
DB_PATH="/tmp/quaid-eval-gbrain-${DATE}.db"
CORPUS_DIR="/tmp/quaid-bench-corpus"
RESULTS_DIR="results"
OUTPUT="${RESULTS_DIR}/gbrain-evals-${QUAID_VERSION}-${DATE}.json"
GBRAIN_EVALS_DIR="/tmp/gbrain-evals"

mkdir -p "$RESULTS_DIR"

echo "=== gbrain-evals Benchmark ==="
echo "Quaid version: $QUAID_VERSION"

# Clone gbrain-evals if not cached
if [ ! -d "$GBRAIN_EVALS_DIR" ]; then
  echo "Cloning garrytan/gbrain-evals..."
  git clone --depth=1 https://github.com/garrytan/gbrain-evals.git "$GBRAIN_EVALS_DIR"
fi

# Set up Quaid DB with corpus
echo "Indexing corpus..."
quaid collection add docs "$CORPUS_DIR" --db "$DB_PATH"

# Run adapter
echo "Running eval adapter..."
python3 benchmarks/gbrain-evals/quaid_adapter.py \
  --db "$DB_PATH" \
  --gbrain-evals-dir "$GBRAIN_EVALS_DIR" \
  --output "$OUTPUT" \
  --quaid-version "$QUAID_VERSION"

echo "Results written to: $OUTPUT"
