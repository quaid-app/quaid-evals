#!/usr/bin/env bash
# setup-corpus.sh - Set up the DAB test corpus for benchmarks
# Creates a standardized 350-page PARA corpus for reproducible benchmarks

set -euo pipefail

CORPUS_DIR="/tmp/quaid-bench-corpus"
CORPUS_REPO="quaid-app/dab-corpus"

echo "Setting up benchmark corpus..."

# Try to clone the official DAB corpus if available
if git clone --depth=1 "https://github.com/${CORPUS_REPO}.git" "$CORPUS_DIR" 2>/dev/null; then
  echo "Cloned official DAB corpus from ${CORPUS_REPO}"
else
  echo "Official corpus not available, generating synthetic corpus..."
  python3 scripts/generate-corpus.py --output "$CORPUS_DIR" --pages 350
fi

echo "Corpus ready at: $CORPUS_DIR"
ls "$CORPUS_DIR" | head -20
echo "Total files: $(find "$CORPUS_DIR" -name '*.md' | wc -l)"
