#!/usr/bin/env bash
# benchmarks/beam/run.sh - BEAM benchmark for Quaid
# Datasets (CC BY-SA 4.0): Mohammadta/BEAM + Mohammadta/BEAM-10M
#
# Run order: 100K -> 500K -> 1M -> 10M
# Requires: OPENAI_API_KEY
# Output: results/beam-<split>-<version>-<date>.json

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
QUAID_BIN="${QUAID_BIN:-quaid}"
DATE=$(date +%Y-%m-%d)
RESULTS_DIR="${RESULTS_DIR:-results}"
SPLIT="${BEAM_SPLIT:-100K}"   # override with BEAM_SPLIT=1M etc
MAX_CONV="${MAX_CONVERSATIONS:-}"
if [[ "${MAX_CONV,,}" == "all" || "${MAX_CONV,,}" == "full" || "$MAX_CONV" == "0" ]]; then
  MAX_CONV=""
fi

python3 "$SCRIPT_DIR/../common/preflight.py" \
  --quaid-bin "$QUAID_BIN" \
  --db "/tmp/quaid-beam-${SPLIT,,}-0000.db" \
  --provider "${LLM_PROVIDER:-openai}" \
  --needs-llm

QUAID_VERSION=$("$QUAID_BIN" --version 2>/dev/null | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1 || echo "unknown")

mkdir -p "$RESULTS_DIR"
OUTPUT="${RESULTS_DIR}/beam-${SPLIT,,}-${QUAID_VERSION}-${DATE}.json"

echo "=== BEAM Benchmark (${SPLIT}) ==="
echo "Quaid version: $QUAID_VERSION"
echo "Provider: ${LLM_PROVIDER:-openai} | Model: ${ANSWERER_MODEL:-gpt-4o}"
echo "Max conversations: ${MAX_CONV:-full split}"

PYTHONUNBUFFERED=1 QUAID_BIN="$QUAID_BIN" python3 "$SCRIPT_DIR/beam_adapter.py" \
  --split "$SPLIT" \
  --output "$OUTPUT" \
  --quaid-version "$QUAID_VERSION" \
  --answerer-model "${ANSWERER_MODEL:-gpt-4o}" \
  --judge-model "${JUDGE_MODEL:-gpt-4o}" \
  --provider "${LLM_PROVIDER:-openai}" \
  --top-k "${TOP_K:-20}" \
  ${MAX_CONV:+--max-conversations "$MAX_CONV"}

echo "Results written to: $OUTPUT"
