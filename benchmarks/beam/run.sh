#!/usr/bin/env bash
# benchmarks/beam/run.sh - BEAM benchmark scaffold
# Requires OPENAI_API_KEY and official BEAM corpus (pending release)

set -euo pipefail

echo "BEAM benchmark scaffold - not yet runnable"
echo "Requires: OPENAI_API_KEY, official BEAM corpus from Mem0"
echo "See benchmarks/beam/README.md for status"
echo ""
echo "When ready, this will:"
echo "  1. Download BEAM 100K/1M/10M conversation corpora"
echo "  2. Index into Quaid DB"
echo "  3. Run BEAM queries"
echo "  4. Score with LLM judge"
echo "  5. Output results/beam-<version>-<date>.json"

# Exit without error so CI doesn't fail on BEAM when it's disabled
exit 0
