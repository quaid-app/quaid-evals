#!/usr/bin/env bash
# setup-corpus.sh - Set up the MSMARCO benchmark corpus for Quaid evals
#
# Strategy:
#   1. If corpus already exists and has queries.json → skip
#   2. Try streaming MSMARCO dev subset from HuggingFace (preferred, ~50MB)
#   3. Fall back to cloning quaid-app/msmarco-corpus (FiQA, 3,165 passages)
#   4. Last resort: generate synthetic corpus

set -euo pipefail

CORPUS_DIR="${CORPUS_DIR:-/tmp/quaid-bench-corpus}"
export CORPUS_DIR

echo "Setting up benchmark corpus at: $CORPUS_DIR"

# Skip if already built
if [ -f "$CORPUS_DIR/queries.json" ]; then
  Q_COUNT=$(python3 -c "import json; print(len(json.load(open('$CORPUS_DIR/queries.json'))))" 2>/dev/null || echo 0)
  if [ "$Q_COUNT" -ge 100 ]; then
    echo "Corpus already exists ($Q_COUNT queries). Skipping build."
    exit 0
  fi
fi

mkdir -p "$CORPUS_DIR"

# Option 1: Stream MSMARCO from HuggingFace (GitHub Actions, unrestricted network)
echo "Attempting MSMARCO streaming from HuggingFace..."
if python3 -c "import datasets" 2>/dev/null || pip install datasets -q 2>/dev/null; then
  if python3 scripts/build-msmarco-subset.py; then
    echo "MSMARCO corpus built successfully."
    exit 0
  fi
fi

echo "HuggingFace streaming unavailable - falling back to FiQA corpus..."

# Option 2: Clone quaid-app/msmarco-corpus (FiQA, pre-built, always available)
FIQA_REPO="quaid-app/msmarco-corpus"
if git clone --depth=1 "https://github.com/${FIQA_REPO}.git" /tmp/fiqa-corpus 2>/dev/null; then
  cp -r /tmp/fiqa-corpus/passages "$CORPUS_DIR/"
  cp /tmp/fiqa-corpus/queries.json "$CORPUS_DIR/" 2>/dev/null || true
  cp /tmp/fiqa-corpus/qrels.json "$CORPUS_DIR/" 2>/dev/null || true
  echo "FiQA corpus ready (${FIQA_REPO})."
  exit 0
fi

# Option 3: Synthetic fallback (no internet, local dev)
echo "Generating synthetic corpus..."
python3 scripts/generate-corpus.py --output "$CORPUS_DIR" --pages 350
echo "Synthetic corpus generated (no ground truth - FTS/semantic tests only)."
