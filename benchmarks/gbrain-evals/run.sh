#!/usr/bin/env bash
# benchmarks/gbrain-evals/run.sh - Run Garry Tan's gbrain-evals against Quaid
# Outputs: results/gbrain-evals-<version>-<date>.json

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
QUAID_BIN="${QUAID_BIN:-quaid}"
DATE=$(date +%Y-%m-%d)
DB_PATH="/tmp/quaid-eval-gbrain-${DATE}.db"
CORPUS_DIR="/tmp/quaid-bench-corpus"
RESULTS_DIR="results"
GBRAIN_EVALS_DIR="/tmp/gbrain-evals"

if [ ! -f "$CORPUS_DIR/queries.json" ]; then
  CORPUS_DIR="$CORPUS_DIR" bash "$SCRIPT_DIR/../../scripts/setup-corpus.sh"
fi

python3 "$SCRIPT_DIR/../common/preflight.py" \
  --quaid-bin "$QUAID_BIN" \
  --db "$DB_PATH" \
  --corpus "$CORPUS_DIR"

QUAID_VERSION=$("$QUAID_BIN" --version 2>/dev/null | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1 || echo "unknown")
OUTPUT="${RESULTS_DIR}/gbrain-evals-${QUAID_VERSION}-${DATE}.json"

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
"$QUAID_BIN" init "$DB_PATH" >/dev/null
"$QUAID_BIN" collection add docs "$CORPUS_DIR/passages" --db "$DB_PATH"
echo "Generating embeddings..."
"$QUAID_BIN" embed --db "$DB_PATH" 2>&1 | tail -1

# Run adapter
echo "Running eval adapter..."
QUAID_BIN="$QUAID_BIN" python3 benchmarks/gbrain-evals/quaid_adapter.py \
  --db "$DB_PATH" \
  --gbrain-evals-dir "$GBRAIN_EVALS_DIR" \
  --queries-file "$CORPUS_DIR/queries.json" \
  --output "$OUTPUT" \
  --quaid-version "$QUAID_VERSION"

echo "Results written to: $OUTPUT"
