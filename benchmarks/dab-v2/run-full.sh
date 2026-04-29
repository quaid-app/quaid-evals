#!/usr/bin/env bash
# benchmarks/dab-v2/run-full.sh
# Full DAB v2 benchmark: §1-§5 against any memory system
#
# Usage:
#   bash benchmarks/dab-v2/run-full.sh                          # Quaid (default)
#   MEMORY_CMD=gbrain bash benchmarks/dab-v2/run-full.sh        # GBrain
#   MEMORY_CMD=qmd bash benchmarks/dab-v2/run-full.sh           # qmd
#
# Systems that score 0 on unsupported sections:
#   qmd:    §3=0 (no conv memory), §4=0 (no graph)
#   GBrain: §3=0 (no conv memory)
#   Mem0:   §2 limited, §4=0 (no graph), §5 limited (needs API)

set -euo pipefail

SYSTEM="${MEMORY_CMD:-quaid}"
VERSION=$(${SYSTEM} --version 2>/dev/null | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1 || echo "unknown")
DATE=$(date +%Y-%m-%d)
DB_PATH="/tmp/dab-v2-full-${SYSTEM}-${DATE}.db"
CORPUS_DIR="/tmp/quaid-bench-corpus"
RESULTS_DIR="results"
OUTPUT="${RESULTS_DIR}/dab-v2-full-${SYSTEM}-${VERSION}-${DATE}.json"

echo "============================================"
echo " DAB v2 Full Benchmark"
echo " System: $SYSTEM $VERSION"
echo " Date: $DATE"
echo "============================================"

mkdir -p "$RESULTS_DIR"

# Set up corpus if needed
if [ ! -f "$CORPUS_DIR/passages/1. Projects/crypto/btc-price-analysis.md" ] 2>/dev/null; then
  echo "Setting up DAB v2 corpus..."
  bash scripts/setup-corpus.sh
fi

# Initialize DB
[ "$SYSTEM" = "quaid" ] && quaid init "$DB_PATH" 2>/dev/null || true

# Run §1 + §2 (Phase 1 script)
echo ""
echo "Running §1 + §2 (Phase 1)..."
MEMORY_CMD="$SYSTEM" DB_PATH="$DB_PATH" CORPUS_DIR="$CORPUS_DIR" \
  bash benchmarks/dab-v2/run.sh 2>&1

# Capture Phase 1 results
S1_SCORE=0
S2_SCORE=0
if [ -f "$RESULTS_DIR/dab-v2-${SYSTEM}-${VERSION}-${DATE}.json" ]; then
  S1_SCORE=$(python3 -c "import json; d=json.load(open('$RESULTS_DIR/dab-v2-${SYSTEM}-${VERSION}-${DATE}.json')); print(d['sections']['s1_infrastructure']['score'])" 2>/dev/null || echo 0)
  S2_SCORE=$(python3 -c "import json; d=json.load(open('$RESULTS_DIR/dab-v2-${SYSTEM}-${VERSION}-${DATE}.json')); print(d['sections']['s2_realworld_retrieval']['score'])" 2>/dev/null || echo 0)
fi

# Run §3 Conversation Memory
echo ""
/opt/homebrew/bin/python3 benchmarks/dab-v2/section3_conversation.py \
  --system "$SYSTEM" \
  --db "$DB_PATH" \
  --output "$RESULTS_DIR/s3-${SYSTEM}-${VERSION}-${DATE}.json" 2>&1
S3_SCORE=$(python3 -c "import json; d=json.load(open('$RESULTS_DIR/s3-${SYSTEM}-${VERSION}-${DATE}.json')); print(d['score'])" 2>/dev/null || echo 0)

# Run §4 Knowledge Graph
echo ""
/opt/homebrew/bin/python3 benchmarks/dab-v2/section4_graph.py \
  --system "$SYSTEM" \
  --db "$DB_PATH" \
  --output "$RESULTS_DIR/s4-${SYSTEM}-${VERSION}-${DATE}.json" 2>&1
S4_SCORE=$(python3 -c "import json; d=json.load(open('$RESULTS_DIR/s4-${SYSTEM}-${VERSION}-${DATE}.json')); print(d['score'])" 2>/dev/null || echo 0)

# Run §5 Agent Intelligence
echo ""
/opt/homebrew/bin/python3 benchmarks/dab-v2/section5_intelligence.py \
  --system "$SYSTEM" \
  --db "$DB_PATH" \
  --output "$RESULTS_DIR/s5-${SYSTEM}-${VERSION}-${DATE}.json" 2>&1
S5_SCORE=$(python3 -c "import json; d=json.load(open('$RESULTS_DIR/s5-${SYSTEM}-${VERSION}-${DATE}.json')); print(d['score'])" 2>/dev/null || echo 0)

# Final summary
TOTAL=$((S1_SCORE + S2_SCORE + S3_SCORE + S4_SCORE + S5_SCORE))
PCT=$(python3 -c "print(round($TOTAL/400*100))")

echo ""
echo "============================================"
echo " DAB v2 Final Results: $SYSTEM $VERSION"
echo "============================================"
echo " §1 Infrastructure:       $S1_SCORE / 40"
echo " §2 Real-World Retrieval: $S2_SCORE / 100"
echo " §3 Conversation Memory:  $S3_SCORE / 100"
echo " §4 Knowledge Graph:      $S4_SCORE / 80"
echo " §5 Agent Intelligence:   $S5_SCORE / 80"
echo "--------------------------------------------"
echo " TOTAL: $TOTAL / 400 ($PCT%)"

if [ "$TOTAL" -ge 340 ]; then echo " Grade: 🟢 Excellent"
elif [ "$TOTAL" -ge 280 ]; then echo " Grade: 🟡 Good"
elif [ "$TOTAL" -ge 200 ]; then echo " Grade: 🟠 Acceptable"
else echo " Grade: 🔴 Needs Work"; fi
echo "============================================"

# Write combined JSON
cat > "$OUTPUT" << JSONEOF
{
  "system": "${SYSTEM}",
  "version": "${VERSION}",
  "date": "${DATE}",
  "benchmark": "dab-v2-full",
  "total": ${TOTAL},
  "max": 400,
  "pct": ${PCT},
  "sections": {
    "s1_infrastructure": {"score": ${S1_SCORE}, "max": 40},
    "s2_realworld_retrieval": {"score": ${S2_SCORE}, "max": 100},
    "s3_conversation_memory": {"score": ${S3_SCORE}, "max": 100},
    "s4_knowledge_graph": {"score": ${S4_SCORE}, "max": 80},
    "s5_agent_intelligence": {"score": ${S5_SCORE}, "max": 80}
  }
}
JSONEOF

echo ""
echo "Full results: $OUTPUT"
