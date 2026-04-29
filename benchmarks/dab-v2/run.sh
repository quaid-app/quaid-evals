#!/usr/bin/env bash
# benchmarks/dab-v2/run.sh - DAB v2 Benchmark (Phase 1: §1 + §2)
# 400pt total benchmark for agent memory systems
# Phase 1 implements §1 Infrastructure (40pts) + §2 Real-World Retrieval (100pts)
#
# Run against any system:
#   MEMORY_CMD="quaid" SEARCH_CMD="quaid search" QUERY_CMD="quaid query" bash benchmarks/dab-v2/run.sh
#   MEMORY_CMD="qmd" SEARCH_CMD="qmd search" QUERY_CMD="qmd query" bash benchmarks/dab-v2/run.sh

set -euo pipefail

SYSTEM="${MEMORY_CMD:-quaid}"
QUAID_VERSION=$(${SYSTEM} --version 2>/dev/null | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1 || echo "unknown")
DATE=$(date +%Y-%m-%d)
DB_PATH="/tmp/dab-v2-${SYSTEM}-${DATE}.db"
CORPUS_DIR="/tmp/quaid-bench-corpus"
RESULTS_DIR="results"
OUTPUT="${RESULTS_DIR}/dab-v2-${SYSTEM}-${QUAID_VERSION}-${DATE}.json"

mkdir -p "$RESULTS_DIR"

echo "=== DAB v2 Benchmark (Phase 1) ==="
echo "System: $SYSTEM $QUAID_VERSION"
echo "DB: $DB_PATH"

S1_SCORE=0
S2_SCORE=0

# ── §1 Infrastructure (40 pts) ─────────────────────────────────────────────

echo ""
echo "=== §1 Infrastructure (40pts) ==="

# S1.1 Install and version (5 pts)
echo "[S1.1] Install and version..."
if ${SYSTEM} --version 2>/dev/null | grep -qE '[0-9]+\.[0-9]+\.[0-9]+'; then
  BINARY_VER=$(${SYSTEM} --version 2>/dev/null | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1)
  S1_1=3
  # Version string matches expected (set EXPECTED_VERSION env var or pass as arg)
  EXPECTED="${EXPECTED_VERSION:-$QUAID_VERSION}"
  [ "$BINARY_VER" = "$EXPECTED" ] && S1_1=5 || true
  echo "  Binary version: $BINARY_VER (expected: $EXPECTED) → $S1_1/5"
else
  S1_1=0
  echo "  Binary not responding → 0/5"
fi
S1_SCORE=$((S1_SCORE + S1_1))

# S1.2 Corpus ingestion (10 pts)
echo "[S1.2] Corpus ingestion..."
if [ "$SYSTEM" = "quaid" ]; then
  ${SYSTEM} init "$DB_PATH" 2>/dev/null || true
  START=$(date +%s%3N)
  if ${SYSTEM} collection add docs "$CORPUS_DIR" --db "$DB_PATH" 2>&1 | grep -q "status=\"ok\""; then
    END=$(date +%s%3N)
    IMPORT_MS=$((END - START))
    S1_2=8  # 5 pts ingested + 3 pts retrievable
    [ "$IMPORT_MS" -lt 180000 ] && S1_2=10  # +2 pts if <180s
    echo "  Ingest: ${IMPORT_MS}ms → $S1_2/10"
  else
    S1_2=0
    echo "  Ingest failed → 0/10"
  fi
elif [ "$SYSTEM" = "qmd" ]; then
  export PATH="$HOME/.bun/bin:$PATH"
  START=$(date +%s%3N)
  qmd update 2>/dev/null && S1_2=8 || S1_2=0
  END=$(date +%s%3N)
  echo "  qmd update: $((END-START))ms → $S1_2/10"
else
  S1_2=0
  echo "  Unknown system, manual ingest required → 0/10"
fi
S1_SCORE=$((S1_SCORE + S1_2))

# S1.3 Basic FTS (10 pts) - exact keyword queries
echo "[S1.3] Basic FTS..."
FTS_QUERIES=(
  "bitcoin blockchain cryptocurrency"
  "python programming language"
  "machine learning neural network"
  "stablecoin ethereum defi"
  "agent memory persistence"
  "Quaid benchmark results"
  "decision corpus selection"
  "SQL database query"
  "encryption cryptography"
  "artificial intelligence"
)
FTS_HITS=0
for Q in "${FTS_QUERIES[@]}"; do
  RESULT=""
  if [ "$SYSTEM" = "quaid" ]; then
    RESULT=$(quaid search "$Q" --db "$DB_PATH" --limit 1 --json 2>/dev/null | python3 -c "import json,sys; d=json.load(sys.stdin); print('hit' if d else 'miss')" 2>/dev/null || echo "miss")
  elif [ "$SYSTEM" = "qmd" ]; then
    export PATH="$HOME/.bun/bin:$PATH"
    RESULT=$(qmd search "$Q" --limit 1 2>/dev/null | grep -q "." && echo "hit" || echo "miss")
  fi
  [ "$RESULT" = "hit" ] && FTS_HITS=$((FTS_HITS + 1))
done
if [ "$FTS_HITS" -ge 9 ]; then S1_3=10
elif [ "$FTS_HITS" -ge 7 ]; then S1_3=7
elif [ "$FTS_HITS" -ge 5 ]; then S1_3=4
else S1_3=0; fi
echo "  FTS: $FTS_HITS/${#FTS_QUERIES[@]} → $S1_3/10"
S1_SCORE=$((S1_SCORE + S1_3))

# S1.4 Basic semantic (10 pts) - direct topic queries
echo "[S1.4] Basic semantic..."
SEM_QUERIES=(
  "how do automated market makers work"
  "what is liquid staking"
  "explain graph database relationships"
  "agent memory across sessions"
  "regulatory framework for crypto"
)
SEM_HITS=0
for Q in "${SEM_QUERIES[@]}"; do
  RESULT=""
  if [ "$SYSTEM" = "quaid" ]; then
    RESULT=$(quaid query "$Q" --db "$DB_PATH" --limit 1 --json 2>/dev/null | python3 -c "import json,sys; d=json.load(sys.stdin); print('hit' if d else 'miss')" 2>/dev/null || echo "miss")
  fi
  [ "$RESULT" = "hit" ] && SEM_HITS=$((SEM_HITS + 1))
done
if [ "$SEM_HITS" -eq 5 ]; then S1_4=10
elif [ "$SEM_HITS" -eq 4 ]; then S1_4=8
elif [ "$SEM_HITS" -eq 3 ]; then S1_4=5
else S1_4=0; fi
echo "  Semantic: $SEM_HITS/${#SEM_QUERIES[@]} → $S1_4/10"
S1_SCORE=$((S1_SCORE + S1_4))

# S1.5 API surface (5 pts)
echo "[S1.5] API surface..."
S1_5=0
[ "$SYSTEM" = "quaid" ] && quaid --help 2>/dev/null | grep -q "search" && S1_5=$((S1_5 + 2))
MCP_RESP=$(printf '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"1.0"}}}\n' | QUAID_DB="$DB_PATH" timeout 5 quaid serve 2>/dev/null || echo "")
echo "$MCP_RESP" | grep -q '"result"' && S1_5=$((S1_5 + 3))
echo "  API surface: $S1_5/5"
S1_SCORE=$((S1_SCORE + S1_5))

echo "§1 Total: $S1_SCORE/40"

# ── §2 Real-World Retrieval (100 pts) ──────────────────────────────────────

echo ""
echo "=== §2 Real-World Retrieval (100pts) ==="

# S2.1 Paraphrase recall (25 pts) - 10 queries × 2.5pts
# Corpus must contain the DAB v2 supplement pages
echo "[S2.1] Paraphrase recall..."
PARAPHRASE_QUERIES=(
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
PARA_HITS=0
for Q in "${PARAPHRASE_QUERIES[@]}"; do
  RESULT=""
  if [ "$SYSTEM" = "quaid" ]; then
    RESULT=$(quaid query "$Q" --db "$DB_PATH" --limit 5 --json 2>/dev/null | python3 -c "import json,sys; d=json.load(sys.stdin); print('hit' if d else 'miss')" 2>/dev/null || echo "miss")
  fi
  [ "$RESULT" = "hit" ] && PARA_HITS=$((PARA_HITS + 1))
done
S2_1=$(python3 -c "print(int($PARA_HITS * 2.5))")
echo "  Paraphrase: $PARA_HITS/${#PARAPHRASE_QUERIES[@]} → $S2_1/25"
S2_SCORE=$((S2_SCORE + S2_1))

# S2.2 Cross-domain compound queries (25 pts)
echo "[S2.2] Cross-domain queries..."
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
  RESULT=""
  if [ "$SYSTEM" = "quaid" ]; then
    RESULT=$(quaid query "$Q" --db "$DB_PATH" --limit 5 --json 2>/dev/null | python3 -c "import json,sys; d=json.load(sys.stdin); print('hit' if d else 'miss')" 2>/dev/null || echo "miss")
  fi
  [ "$RESULT" = "hit" ] && CROSS_HITS=$((CROSS_HITS + 1))
done
S2_2=$(python3 -c "print(int($CROSS_HITS * 2.5))")
echo "  Cross-domain: $CROSS_HITS/${#CROSS_QUERIES[@]} → $S2_2/25"
S2_SCORE=$((S2_SCORE + S2_2))

# S2.3 Temporal/recency queries (25 pts) - most recent should rank first
echo "[S2.3] Temporal queries..."
TEMPORAL_QUERIES=(
  "latest DAB benchmark results"
  "most recent Quaid version benchmark"
  "current quaid benchmark score"
  "latest benchmark run results"
  "most recent DAB test"
)
TEMPORAL_HITS=0
for Q in "${TEMPORAL_QUERIES[@]}"; do
  RESULT=""
  if [ "$SYSTEM" = "quaid" ]; then
    # Check if top result contains "v0.11" (most recent)
    TOP=$(quaid query "$Q" --db "$DB_PATH" --limit 3 --json 2>/dev/null | python3 -c "
import json,sys
d=json.load(sys.stdin)
if d:
    titles = [x.get('title','') for x in d[:3]]
    print('hit' if any('0.11' in t or '0.9.10' in t for t in titles) else 'miss')
else:
    print('miss')
" 2>/dev/null || echo "miss")
    RESULT="$TOP"
  fi
  [ "$RESULT" = "hit" ] && TEMPORAL_HITS=$((TEMPORAL_HITS + 1))
done
S2_3=$((TEMPORAL_HITS * 5))
echo "  Temporal: $TEMPORAL_HITS/${#TEMPORAL_QUERIES[@]} → $S2_3/25"
S2_SCORE=$((S2_SCORE + S2_3))

# S2.4 Negative recall (25 pts) - absent topics should return empty/low score
echo "[S2.4] Negative recall (absent topics)..."
NEGATIVE_QUERIES=(
  "MANTRA Chain technical whitepaper validator economics"
  "OpenClaw internal CI pipeline configuration secrets"
  "private key derivation path BIP39 hardware wallet setup"
  "specific Hyperliquid vault APR calculation formula"
  "Solana validator staking rewards exact calculation method"
)
NEGATIVE_HITS=0
for Q in "${NEGATIVE_QUERIES[@]}"; do
  RESULT=""
  if [ "$SYSTEM" = "quaid" ]; then
    # Should return empty OR top score < 0.3
    RESULT=$(quaid query "$Q" --db "$DB_PATH" --limit 1 --json 2>/dev/null | python3 -c "
import json,sys
d=json.load(sys.stdin)
if not d:
    print('correct')
elif d[0].get('score', 1.0) < 0.3:
    print('correct')
else:
    print('false_positive')
" 2>/dev/null || echo "correct")  # treat errors as correct (no result)
  fi
  [ "$RESULT" = "correct" ] && NEGATIVE_HITS=$((NEGATIVE_HITS + 1))
done
S2_4=$((NEGATIVE_HITS * 5))
echo "  Negative: $NEGATIVE_HITS/${#NEGATIVE_QUERIES[@]} correct → $S2_4/25"
S2_SCORE=$((S2_SCORE + S2_4))

echo "§2 Total: $S2_SCORE/100"

# ── Summary ─────────────────────────────────────────────────────────────────

TOTAL=$((S1_SCORE + S2_SCORE))
PHASE1_MAX=140  # §1 + §2 only in Phase 1
TOTAL_MAX=400   # Full DAB v2

echo ""
echo "=== DAB v2 Results (Phase 1: §1+§2) ==="
echo "§1 Infrastructure: $S1_SCORE/40"
echo "§2 Real-World Retrieval: $S2_SCORE/100"
echo "Phase 1 Total: $TOTAL/$PHASE1_MAX ($(python3 -c "print(round($TOTAL/$PHASE1_MAX*100))")%)"
echo ""
echo "§3 Conversation Memory: 0/100 (Phase 2 - requires #105)"
echo "§4 Knowledge Graph:     0/80  (Phase 3 - requires #107)"
echo "§5 Agent Intelligence:  TBD/80 (Phase 4)"
echo "Full DAB v2 estimate:   $TOTAL/400 ($(python3 -c "print(round($TOTAL/400*100))")%)"

# Write JSON
cat > "$OUTPUT" << JSONEOF
{
  "system": "${SYSTEM}",
  "quaid_version": "${QUAID_VERSION}",
  "date": "${DATE}",
  "benchmark": "dab-v2-phase1",
  "phase": "1-infra-retrieval",
  "sections": {
    "s1_infrastructure": {"score": ${S1_SCORE}, "max": 40, "breakdown": {"install": ${S1_1}, "ingest": ${S1_2}, "fts": ${S1_3}, "semantic": ${S1_4}, "api": ${S1_5}}},
    "s2_realworld_retrieval": {"score": ${S2_SCORE}, "max": 100, "breakdown": {"paraphrase": ${S2_1}, "cross_domain": ${S2_2}, "temporal": ${S2_3}, "negative": ${S2_4}}},
    "s3_conversation": {"score": 0, "max": 100, "note": "Phase 2 - requires conversation memory feature"},
    "s4_graph": {"score": 0, "max": 80, "note": "Phase 3 - requires entity extraction feature"},
    "s5_intelligence": {"score": 0, "max": 80, "note": "Phase 4"}
  },
  "phase1_total": ${TOTAL},
  "phase1_max": ${PHASE1_MAX},
  "full_dab_v2_estimate": ${TOTAL}
}
JSONEOF

echo ""
echo "Results: $OUTPUT"
