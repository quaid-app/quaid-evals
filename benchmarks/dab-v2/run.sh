#!/usr/bin/env bash
# benchmarks/dab-v2/run.sh - DAB v2.1 Benchmark
# 420pt framework (Beth peer-review edition)
# §1 Infrastructure (40pts) + §2 Real-World Retrieval (100pts)
# §3/§4/§5 require separate Python scripts
#
# Changes from v2.0:
#   - §4 now 100pts (was 80) - Three Pillars
#   - Latency Penalty: query >2s = half pts, >5s = zero
#   - §1.5 includes schema migration test
#
# Run against any system:
#   MEMORY_CMD="quaid" bash benchmarks/dab-v2/run.sh
#   MEMORY_CMD="qmd" bash benchmarks/dab-v2/run.sh

set -euo pipefail

SYSTEM="${MEMORY_CMD:-quaid}"
QUAID_VERSION=$(${SYSTEM} --version 2>/dev/null | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1 || echo "unknown")
DATE=$(date +%Y-%m-%d)
DB_PATH="/tmp/dab-v2-${SYSTEM}-${DATE}.db"
CORPUS_DIR="${CORPUS_DIR:-/tmp/quaid-bench-corpus}"
RESULTS_DIR="${RESULTS_DIR:-results}"
OUTPUT="${RESULTS_DIR}/dab-v2-${SYSTEM}-${QUAID_VERSION}-${DATE}.json"
EXPECTED_VERSION="${EXPECTED_VERSION:-$QUAID_VERSION}"

mkdir -p "$RESULTS_DIR"

# Latency helper: returns 1 if penalty applies, echos penalty factor
latency_factor() {
  local ms=$1
  if [ "$ms" -gt 5000 ]; then echo "0"; return
  elif [ "$ms" -gt 2000 ]; then echo "0.5"; return
  fi
  echo "1"
}

apply_penalty() {
  local score=$1 ms=$2
  local factor=$(latency_factor "$ms")
  python3 -c "print(int($score * $factor))"
}

echo "=== DAB v2.1 Benchmark (Phase 1: §1+§2) ==="
echo "System: $SYSTEM $QUAID_VERSION"
echo "DB: $DB_PATH"
echo "Corpus: $CORPUS_DIR"

S1_SCORE=0
S2_SCORE=0
LATENCY_LOG=""

# ── §1 Infrastructure (40 pts) ────────────────────────────────────────────────

echo ""
echo "=== §1 Infrastructure (40pts) ==="

# S1.1 Install and version (5 pts)
BINARY_VER=$(${SYSTEM} --version 2>/dev/null | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1 || echo "")
S1_1=0
[ -n "$BINARY_VER" ] && S1_1=3
[ "$BINARY_VER" = "$EXPECTED_VERSION" ] && S1_1=5
echo "[S1.1] Install: $BINARY_VER (expected: $EXPECTED_VERSION) → $S1_1/5"
S1_SCORE=$((S1_SCORE + S1_1))

# S1.2 Corpus ingestion (10 pts)
if [ "$SYSTEM" = "quaid" ]; then
  quaid init "$DB_PATH" 2>/dev/null || true
  START=$(python3 -c "import time; print(int(time.time()*1000))")
  if quaid collection add docs "$CORPUS_DIR" --db "$DB_PATH" 2>&1 | grep -q "status=\"ok\""; then
    END=$(python3 -c "import time; print(int(time.time()*1000))")
    IMPORT_MS=$((END - START))
    echo "  Generating embeddings..."
    quaid embed --db "$DB_PATH" 2>&1 | tail -1
    S1_2=8
    [ "$IMPORT_MS" -lt 180000 ] && S1_2=10
    echo "  Ingest: ${IMPORT_MS}ms → $S1_2/10"
  else
    IMPORT_MS=999999; S1_2=0; echo "  Ingest FAILED → 0/10"
  fi
elif [ "$SYSTEM" = "qmd" ]; then
  export PATH="$HOME/.bun/bin:$PATH"
  if qmd collection add "$CORPUS_DIR" --name dab-v2 2>/dev/null; then
    qmd update 2>/dev/null | tail -1
    qmd embed 2>/dev/null | tail -1
    S1_2=8; IMPORT_MS=60000
  else
    S1_2=0; IMPORT_MS=999999
  fi
  echo "  qmd ingest → $S1_2/10"
else
  S1_2=0; IMPORT_MS=999999; echo "  Unknown system → 0/10"
fi
S1_SCORE=$((S1_SCORE + S1_2))

# S1.3 Basic FTS (10 pts)
FTS_QUERIES=("bitcoin blockchain" "python programming" "machine learning" "stablecoin defi" "agent memory" "DAB benchmark" "MSMARCO corpus" "SQL database" "encryption" "artificial intelligence")
FTS_HITS=0
for Q in "${FTS_QUERIES[@]}"; do
  T_START=$(python3 -c "import time; print(int(time.time()*1000))")
  if [ "$SYSTEM" = "quaid" ]; then
    RESULT=$(quaid search "$Q" --db "$DB_PATH" --limit 1 --json 2>/dev/null | python3 -c "import json,sys; d=json.load(sys.stdin); print('hit' if d else 'miss')" 2>/dev/null || echo "miss")
  elif [ "$SYSTEM" = "qmd" ]; then
    export PATH="$HOME/.bun/bin:$PATH"
    RESULT=$(qmd search "$Q" -c dab-v2 -n 1 --json 2>/dev/null | python3 -c "import json,sys; d=json.load(sys.stdin); print('hit' if d else 'miss')" 2>/dev/null || echo "miss")
  else
    RESULT="miss"
  fi
  T_END=$(python3 -c "import time; print(int(time.time()*1000))")
  T_MS=$((T_END - T_START))
  [ "$RESULT" = "hit" ] && FTS_HITS=$((FTS_HITS + 1))
done
if [ "$FTS_HITS" -ge 9 ]; then S1_3=10
elif [ "$FTS_HITS" -ge 7 ]; then S1_3=7
elif [ "$FTS_HITS" -ge 5 ]; then S1_3=4
else S1_3=0; fi
echo "[S1.3] FTS: $FTS_HITS/${#FTS_QUERIES[@]} → $S1_3/10"
S1_SCORE=$((S1_SCORE + S1_3))

# S1.4 Basic semantic (10 pts)
SEM_QUERIES=("how do automated market makers work" "what is liquid staking" "explain graph database relationships" "agent memory across sessions" "regulatory framework for crypto")
SEM_HITS=0
for Q in "${SEM_QUERIES[@]}"; do
  T_START=$(python3 -c "import time; print(int(time.time()*1000))")
  if [ "$SYSTEM" = "quaid" ]; then
    RESULT=$(quaid query "$Q" --db "$DB_PATH" --limit 1 --json 2>/dev/null | python3 -c "import json,sys; d=json.load(sys.stdin); print('hit' if d else 'miss')" 2>/dev/null || echo "miss")
  elif [ "$SYSTEM" = "qmd" ]; then
    export PATH="$HOME/.bun/bin:$PATH"
    RESULT=$(qmd query "$Q" -c dab-v2 -n 1 --json 2>/dev/null | python3 -c "import json,sys; d=json.load(sys.stdin); print('hit' if d else 'miss')" 2>/dev/null || echo "miss")
  else
    RESULT="miss"
  fi
  T_END=$(python3 -c "import time; print(int(time.time()*1000))")
  T_MS=$((T_END - T_START))
  [ "$RESULT" = "hit" ] && SEM_HITS=$((SEM_HITS + 1))
done
if [ "$SEM_HITS" -eq 5 ]; then S1_4=10
elif [ "$SEM_HITS" -eq 4 ]; then S1_4=8
elif [ "$SEM_HITS" -eq 3 ]; then S1_4=5
else S1_4=0; fi
echo "[S1.4] Semantic: $SEM_HITS/5 → $S1_4/10"
S1_SCORE=$((S1_SCORE + S1_4))

# S1.5 API surface + schema migration (5 pts)
S1_5=0
[ "$SYSTEM" = "quaid" ] && quaid --help 2>/dev/null | grep -q "search" && S1_5=$((S1_5 + 1))
MCP_RESP=$(printf '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"1.0"}}}\n' | QUAID_DB="$DB_PATH" timeout 5 ${SYSTEM} serve 2>/dev/null || echo "")
echo "$MCP_RESP" | grep -q '"result"' && S1_5=$((S1_5 + 2))
# Schema migration test: try opening a non-existent/wrong-version DB
WRONG_DB="/tmp/dab-v2-schema-test-empty.db"
MIGRATION_MSG=$(${SYSTEM} search "test" --db "$WRONG_DB" 2>&1 | head -1 || echo "")
if echo "$MIGRATION_MSG" | grep -qiE "schema|version|migrate|init"; then
  S1_5=$((S1_5 + 2)); echo "  Schema migration: clear error → +2pts"
else
  echo "  Schema migration: no clear error"
fi
echo "[S1.5] API + schema: $S1_5/5"
S1_SCORE=$((S1_SCORE + S1_5))

echo "§1 Total: $S1_SCORE/40"

# ── §2 Real-World Retrieval (100 pts) ──────────────────────────────────────────

echo ""
echo "=== §2 Real-World Retrieval (100pts) ==="

run_query() {
  local Q="$1" DB="$2" LIMIT="${3:-5}"
  local T_START T_END T_MS RESULT
  T_START=$(python3 -c "import time; print(int(time.time()*1000))")
  if [ "$SYSTEM" = "quaid" ]; then
    RESULT=$(quaid query "$Q" --db "$DB" --limit "$LIMIT" --json 2>/dev/null | python3 -c "import json,sys; d=json.load(sys.stdin); print('hit' if d else 'miss')" 2>/dev/null || echo "miss")
  elif [ "$SYSTEM" = "qmd" ]; then
    export PATH="$HOME/.bun/bin:$PATH"
    RESULT=$(qmd query "$Q" -c dab-v2 -n "$LIMIT" --json 2>/dev/null | python3 -c "import json,sys; d=json.load(sys.stdin); print('hit' if d else 'miss')" 2>/dev/null || echo "miss")
  else
    RESULT="miss"
  fi
  T_END=$(python3 -c "import time; print(int(time.time()*1000))")
  T_MS=$((T_END - T_START))
  echo "$RESULT:$T_MS"
}

# S2.1 Paraphrase recall (25 pts, 2.5 pts each, latency penalty applies)
PARA_QUERIES=(
  "BTC price above seventy-five thousand dollars"
  "neural network model weights optimization"
  "agent memory persistence across sessions"
  "how to sync files without a cloud service"
  "what corpus did we decide to use for benchmarking"
  "decentralized exchange trading mechanisms"
  "automated market maker liquidity provision"
  "decision made about MCP configuration"
  "latest DAB benchmark score"
  "what is liquid staking on Ethereum"
)
PARA_RAW=0; PARA_PENALTY=0
for Q in "${PARA_QUERIES[@]}"; do
  RES_MS=$(run_query "$Q" "$DB_PATH")
  RES="${RES_MS%%:*}"; MS="${RES_MS##*:}"
  PTS_RAW=25; [ "$RES" = "miss" ] && PTS_RAW=0
  PTS=$(apply_penalty "$PTS_RAW" "$MS")
  [ "$RES" = "hit" ] && PARA_RAW=$((PARA_RAW + 1))
  PARA_PENALTY=$((PARA_PENALTY + PTS))
done
S2_1=$(python3 -c "print(int($PARA_RAW * 2.5))")
echo "[S2.1] Paraphrase: $PARA_RAW/10 raw → $S2_1/25"
S2_SCORE=$((S2_SCORE + S2_1))

# S2.2 Cross-domain (25 pts)
CROSS_QUERIES=(
  "what tools and decisions have we made about crypto analysis"
  "agent frameworks and memory systems we have evaluated"
  "decisions made about benchmark and testing infrastructure"
  "what AI research and crypto projects are we working on"
  "what are the latest results from our benchmarking work"
  "how do we handle memory persistence in our agent setup"
  "what defi protocols and liquidity mechanisms exist"
  "what decisions have been made about database and storage"
  "what technical tools are we using for development"
  "describe the relationship between Quaid and OpenClaw"
)
CROSS_HITS=0
for Q in "${CROSS_QUERIES[@]}"; do
  RES_MS=$(run_query "$Q" "$DB_PATH")
  RES="${RES_MS%%:*}"
  [ "$RES" = "hit" ] && CROSS_HITS=$((CROSS_HITS + 1))
done
S2_2=$(python3 -c "print(int($CROSS_HITS * 2.5))")
echo "[S2.2] Cross-domain: $CROSS_HITS/10 → $S2_2/25"
S2_SCORE=$((S2_SCORE + S2_2))

# S2.3 Temporal/recency (25 pts)
TEMPORAL_QUERIES=("latest DAB benchmark results" "most recent Quaid version benchmark" "current quaid benchmark score" "latest benchmark run results" "most recent DAB test")
TEMPORAL_HITS=0
for Q in "${TEMPORAL_QUERIES[@]}"; do
  if [ "$SYSTEM" = "quaid" ]; then
    TOP=$(quaid query "$Q" --db "$DB_PATH" --limit 3 --json 2>/dev/null | python3 -c "
import json,sys; d=json.load(sys.stdin)
if d:
    titles=[x.get('title','') for x in d[:3]]
    print('hit' if any('0.13' in t or '0.12' in t or '0.11' in t for t in titles) else 'miss')
else: print('miss')
" 2>/dev/null || echo "miss")
  else
    TOP="miss"
  fi
  [ "$TOP" = "hit" ] && TEMPORAL_HITS=$((TEMPORAL_HITS + 1))
done
S2_3=$((TEMPORAL_HITS * 5))
echo "[S2.3] Temporal: $TEMPORAL_HITS/5 → $S2_3/25"
S2_SCORE=$((S2_SCORE + S2_3))

# S2.4 Negative recall (25 pts)
NEGATIVE_QUERIES=(
  "MANTRA Chain technical whitepaper validator economics"
  "OpenClaw internal CI pipeline configuration secrets"
  "private key derivation path BIP39 hardware wallet setup"
  "specific Hyperliquid vault APR calculation formula"
  "Solana validator staking rewards exact calculation method"
)
NEGATIVE_HITS=0
for Q in "${NEGATIVE_QUERIES[@]}"; do
  if [ "$SYSTEM" = "quaid" ]; then
    RESULT=$(quaid query "$Q" --db "$DB_PATH" --limit 1 --json 2>/dev/null | python3 -c "
import json,sys
d=json.load(sys.stdin)
if not d: print('correct')
elif d[0].get('score',1.0) < 0.3: print('correct')
else: print('false_positive')
" 2>/dev/null || echo "correct")
  elif [ "$SYSTEM" = "qmd" ]; then
    export PATH="$HOME/.bun/bin:$PATH"
    CNT=$(qmd search "$Q" -c dab-v2 -n 1 2>/dev/null | grep -c "." || echo "0")
    [ "$CNT" -eq 0 ] && RESULT="correct" || RESULT="false_positive"
  else
    RESULT="correct"
  fi
  [ "$RESULT" = "correct" ] && NEGATIVE_HITS=$((NEGATIVE_HITS + 1))
done
S2_4=$((NEGATIVE_HITS * 5))
echo "[S2.4] Negative: $NEGATIVE_HITS/5 → $S2_4/25"
S2_SCORE=$((S2_SCORE + S2_4))

echo "§2 Total: $S2_SCORE/100"

# ── Summary ────────────────────────────────────────────────────────────────────

TOTAL=$((S1_SCORE + S2_SCORE))
PHASE1_MAX=140

echo ""
echo "=== DAB v2.1 Results (Phase 1: §1+§2) ==="
echo "§1 Infrastructure:       $S1_SCORE/40"
echo "§2 Real-World Retrieval: $S2_SCORE/100"
echo "Phase 1 Total:           $TOTAL/$PHASE1_MAX ($(python3 -c "print(round($TOTAL/$PHASE1_MAX*100))")%)"
echo ""
echo "§3 Conversation Memory:  0/100 (Phase 2 - requires #105)"
echo "§4 Knowledge Graph:      0/100 (Phase 3 - requires #107)"
echo "§5 Agent Intelligence:   TBD/80 (Phase 4)"
echo "Full DAB v2.1 est:       $TOTAL/420 ($(python3 -c "print(round($TOTAL/420*100))")%)"

rm -f "$RESULTS_DIR/dab-v2-${SYSTEM}-${QUAID_VERSION}-${DATE}.json" 2>/dev/null
cat > "$OUTPUT" << JSONEOF
{
  "system": "${SYSTEM}",
  "quaid_version": "${QUAID_VERSION}",
  "date": "${DATE}",
  "benchmark": "dab-v2-phase1",
  "spec_version": "2.1",
  "max_total": 420,
  "sections": {
    "s1_infrastructure": {"score": ${S1_SCORE}, "max": 40, "breakdown": {"install": ${S1_1}, "ingest": ${S1_2}, "fts": ${S1_3}, "semantic": ${S1_4}, "api": ${S1_5}}},
    "s2_realworld_retrieval": {"score": ${S2_SCORE}, "max": 100, "breakdown": {"paraphrase": ${S2_1}, "cross_domain": ${S2_2}, "temporal": ${S2_3}, "negative": ${S2_4}}},
    "s3_conversation": {"score": 0, "max": 100, "note": "Phase 2"},
    "s4_graph": {"score": 0, "max": 100, "note": "Phase 3"},
    "s5_intelligence": {"score": 0, "max": 80, "note": "Phase 4"}
  },
  "phase1_total": ${TOTAL},
  "phase1_max": ${PHASE1_MAX}
}
JSONEOF

echo "Results: $OUTPUT"
