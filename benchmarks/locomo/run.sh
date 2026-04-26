#!/usr/bin/env bash
# benchmarks/locomo/run.sh - Run LoCoMo benchmark against Quaid
# LoCoMo: 10 multi-session dialogues, ~300 questions
# Tests: factual recall, temporal reasoning, multi-hop inference
#
# Requires: OPENAI_API_KEY (for LLM answer generation + judge)
# Optional:  ANTHROPIC_API_KEY (pass --provider anthropic to use Claude instead)
#
# Outputs: results/locomo-<version>-<date>.json

set -euo pipefail

QUAID_VERSION=$(quaid --version 2>/dev/null | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1 || echo "unknown")
DATE=$(date +%Y-%m-%d)
DB_PATH="/tmp/quaid-eval-locomo-${DATE}.db"
CORPUS_DIR="/tmp/quaid-bench-corpus"
RESULTS_DIR="results"
OUTPUT="${RESULTS_DIR}/locomo-${QUAID_VERSION}-${DATE}.json"
BENCHMARKS_DIR="/tmp/memory-benchmarks"

mkdir -p "$RESULTS_DIR"

echo "=== LoCoMo Benchmark ==="
echo "Quaid version: $QUAID_VERSION"

# Clone memory-benchmarks if not cached
if [ ! -d "$BENCHMARKS_DIR" ]; then
  echo "Cloning mem0ai/memory-benchmarks..."
  git clone --depth=1 https://github.com/mem0ai/memory-benchmarks.git "$BENCHMARKS_DIR"
fi

cd "$BENCHMARKS_DIR"
pip install -r requirements.txt -q

# Run LoCoMo via the Quaid adapter
echo "Running LoCoMo adapter..."
python3 "$OLDPWD/benchmarks/locomo/quaid_adapter.py" \
  --db "$DB_PATH" \
  --benchmarks-dir "$BENCHMARKS_DIR" \
  --output "$OLDPWD/$OUTPUT" \
  --quaid-version "$QUAID_VERSION" \
  --answerer-model "${ANSWERER_MODEL:-gpt-4o}" \
  --judge-model "${JUDGE_MODEL:-gpt-4o}" \
  --provider "${LLM_PROVIDER:-openai}" \
  --top-k 50

echo "Results written to: $OUTPUT"
