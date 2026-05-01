#!/usr/bin/env bash
# benchmarks/longmemeval/run.sh - Run LongMemEval against Quaid
# LongMemEval (ICLR 2025): 500 questions, 6 types, per-question ingest
# Mem0 v3 reference: 93.4% overall
#
# Requires: OPENAI_API_KEY (or ANTHROPIC_API_KEY with LLM_PROVIDER=anthropic)
# Output: results/longmemeval-<version>-<date>.json

set -euo pipefail

QUAID_VERSION=$(quaid --version 2>/dev/null | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1 || echo "unknown")
DATE=$(date +%Y-%m-%d)
DB_BASE="/tmp/quaid-eval-lme-${DATE}"
RESULTS_DIR="${RESULTS_DIR:-results}"
OUTPUT="${RESULTS_DIR}/longmemeval-${QUAID_VERSION}-${DATE}.json"

mkdir -p "$RESULTS_DIR"

echo "=== LongMemEval Benchmark ==="
echo "Quaid version: $QUAID_VERSION"
echo "Provider: ${LLM_PROVIDER:-openai} | Model: ${ANSWERER_MODEL:-gpt-4o}"

python3 "$(dirname "$0")/quaid_adapter.py" \
  --db "$DB_BASE" \
  --output "$OUTPUT" \
  --quaid-version "$QUAID_VERSION" \
  --answerer-model "${ANSWERER_MODEL:-gpt-4o}" \
  --judge-model "${JUDGE_MODEL:-gpt-4o}" \
  --provider "${LLM_PROVIDER:-openai}" \
  --top-k "${TOP_K:-20}" \
  ${MAX_QUESTIONS:+--max-questions "$MAX_QUESTIONS"} \
  ${SKIP_EMBED:+--skip-embed}

echo "Results written to: $OUTPUT"
