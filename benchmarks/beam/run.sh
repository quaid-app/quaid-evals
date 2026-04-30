#!/usr/bin/env bash
# benchmarks/beam/run.sh - BEAM benchmark for Quaid
# Datasets (CC BY-SA 4.0): Mohammadta/BEAM + Mohammadta/BEAM-10M
#
# Run order: 100K -> 500K -> 1M -> 10M
# Requires: OPENAI_API_KEY
# Output: results/beam-<split>-<version>-<date>.json

set -euo pipefail

QUAID_VERSION=$(quaid --version 2>/dev/null | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1 || echo "unknown")
DATE=$(date +%Y-%m-%d)
RESULTS_DIR="${RESULTS_DIR:-results}"
SPLIT="${BEAM_SPLIT:-100K}"   # override with BEAM_SPLIT=1M etc
MAX_CONV="${MAX_CONVERSATIONS:-}"

mkdir -p "$RESULTS_DIR"
OUTPUT="${RESULTS_DIR}/beam-${SPLIT,,}-${QUAID_VERSION}-${DATE}.json"

echo "=== BEAM Benchmark (${SPLIT}) ==="
echo "Quaid version: $QUAID_VERSION"
echo "Provider: ${LLM_PROVIDER:-openai} | Model: ${ANSWERER_MODEL:-gpt-4o}"

python3 "$(dirname "$0")/beam_adapter.py" \
  --split "$SPLIT" \
  --output "$OUTPUT" \
  --quaid-version "$QUAID_VERSION" \
  --answerer-model "${ANSWERER_MODEL:-gpt-4o}" \
  --judge-model "${JUDGE_MODEL:-gpt-4o}" \
  --provider "${LLM_PROVIDER:-openai}" \
  --top-k "${TOP_K:-20}" \
  ${MAX_CONV:+--max-conversations "$MAX_CONV"}

echo "Results written to: $OUTPUT"
