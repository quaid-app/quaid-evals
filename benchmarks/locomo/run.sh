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

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
QUAID_BIN="${QUAID_BIN:-quaid}"
DATE=$(date +%Y-%m-%d)
DB_PATH="/tmp/quaid-eval-locomo-${DATE}.db"
CORPUS_DIR="/tmp/quaid-bench-corpus"
RESULTS_DIR="results"
BENCHMARKS_DIR="/tmp/memory-benchmarks"

python3 "$SCRIPT_DIR/../common/preflight.py" \
  --quaid-bin "$QUAID_BIN" \
  --db "$DB_PATH" \
  --provider "${LLM_PROVIDER:-openai}" \
  --needs-llm \
  --needs-extraction

QUAID_VERSION=$("$QUAID_BIN" --version 2>/dev/null | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1 || echo "unknown")
OUTPUT="${RESULTS_DIR}/locomo-${QUAID_VERSION}-${DATE}.json"
MAX_QUESTIONS_ARG=()
if [ -n "${MAX_QUESTIONS:-}" ]; then
  MAX_QUESTIONS_ARG=(--max-questions "$MAX_QUESTIONS")
fi
INGEST_SCOPE="${LOCOMO_INGEST_SCOPE:-full}"

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
QUAID_BIN="$QUAID_BIN" python3 "$OLDPWD/benchmarks/locomo/quaid_adapter.py" \
  --db "$DB_PATH" \
  --benchmarks-dir "$BENCHMARKS_DIR" \
  --output "$OLDPWD/$OUTPUT" \
  --quaid-version "$QUAID_VERSION" \
  --answerer-model "${ANSWERER_MODEL:-gpt-4o}" \
  --judge-model "${JUDGE_MODEL:-gpt-4o}" \
  --provider "${LLM_PROVIDER:-openai}" \
  --top-k 50 \
  --ingest-scope "$INGEST_SCOPE" \
  "${MAX_QUESTIONS_ARG[@]}"

echo "Results written to: $OUTPUT"
