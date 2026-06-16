#!/usr/bin/env bash
# benchmarks/dab/run.sh - Run the Doug Aillm Benchmark against Quaid
# Outputs: results/dab-<version>-<date>.json

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
QUAID_BIN="${QUAID_BIN:-quaid}"
DATE=$(date +%Y-%m-%d)
DB_PATH="/tmp/quaid-eval-dab-${DATE}.db"
CORPUS_DIR="/tmp/quaid-bench-corpus"
RESULTS_DIR="results"

if [ ! -f "$CORPUS_DIR/queries.json" ]; then
  CORPUS_DIR="$CORPUS_DIR" bash "$SCRIPT_DIR/../../scripts/setup-corpus.sh"
fi

python3 "$SCRIPT_DIR/../common/preflight.py" \
  --quaid-bin "$QUAID_BIN" \
  --db "$DB_PATH" \
  --corpus "$CORPUS_DIR"

QUAID_VERSION=$("$QUAID_BIN" --version 2>/dev/null | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1 || echo "unknown")
OUTPUT="${RESULTS_DIR}/dab-${QUAID_VERSION}-${DATE}.json"

mkdir -p "$RESULTS_DIR"

echo "=== DAB Benchmark ==="
echo "Quaid version: $QUAID_VERSION"
echo "DB: $DB_PATH"
echo "Corpus: $CORPUS_DIR"

json_has_relevant_hit() {
  local query="$1"
  python3 -c '
import json, re, sys
query = sys.argv[1].lower()
tokens = {t for t in re.findall(r"[a-z0-9]+", query) if len(t) > 3}
try:
    data = json.load(sys.stdin)
except Exception:
    print("invalid")
    raise SystemExit(0)
if isinstance(data, dict):
    data = data.get("results") or data.get("items") or data.get("matches") or []
if not isinstance(data, list) or not data:
    print("miss")
    raise SystemExit(0)
for item in data[:5]:
    if not isinstance(item, dict):
        continue
    text = " ".join(str(item.get(k, "")) for k in ("title", "slug", "summary", "snippet", "content", "text")).lower()
    if not tokens or any(t in text for t in tokens):
        print("hit")
        raise SystemExit(0)
print("miss")
' "$query"
}

# Section 1: Install check (already installed)
echo ""
echo "[1/8] Install check..."
"$QUAID_BIN" --version && INSTALL_SCORE=10 || INSTALL_SCORE=0
echo "Install score: $INSTALL_SCORE/10"

# Section 2: Collection add
echo ""
echo "[2/8] Collection add..."
"$QUAID_BIN" init "$DB_PATH" >/dev/null
START=$(date +%s%3N)
if "$QUAID_BIN" collection add docs "$CORPUS_DIR" --db "$DB_PATH" 2>&1; then
  END=$(date +%s%3N)
  COLLECTION_ELAPSED=$(( END - START ))
  IMPORT_SCORE=30
  echo "Collection add: ${COLLECTION_ELAPSED}ms"
  # Generate embeddings for semantic search
  echo "  Generating embeddings..."
  "$QUAID_BIN" embed --db "$DB_PATH" 2>&1 | tail -1
else
  COLLECTION_ELAPSED=99999
  IMPORT_SCORE=0
  echo "Collection add FAILED"
fi

# Section 3: FTS search
echo ""
echo "[3/8] FTS search..."
FTS_SCORE=0
FTS_LATENCY=0
FTS_QUERIES=(
  "agent memory architecture"
  "DeFi liquidity"
  "Rust performance"
  "stablecoin regulation"
  "vector embeddings"
)
FTS_PASS=0
for QUERY in "${FTS_QUERIES[@]}"; do
  START=$(date +%s%3N)
  RESULT=$("$QUAID_BIN" search "$QUERY" --db "$DB_PATH" --limit 5 --json 2>/dev/null || echo "")
  END=$(date +%s%3N)
  ELAPSED=$(( END - START ))
  FTS_LATENCY=$(( FTS_LATENCY + ELAPSED ))
  if [ "$(printf '%s' "$RESULT" | json_has_relevant_hit "$QUERY")" = "hit" ]; then
    FTS_PASS=$(( FTS_PASS + 1 ))
  fi
done
FTS_LATENCY=$(( FTS_LATENCY / ${#FTS_QUERIES[@]} ))
FTS_SCORE=$(( FTS_PASS * 8 ))  # 8 pts per query, max 40
echo "FTS: ${FTS_PASS}/${#FTS_QUERIES[@]} queries returned results, avg ${FTS_LATENCY}ms"

# Section 4: Semantic search
echo ""
echo "[4/8] Semantic search..."
SEM_SCORE=0
SEM_LATENCY=0
SEM_QUERIES=(
  "how do agents remember things across sessions"
  "decentralized exchange mechanics"
  "memory efficient retrieval at scale"
  "organizing knowledge for productivity"
  "cross-chain bridge security"
  "token supply and demand dynamics"
)
SEM_PASS=0
for QUERY in "${SEM_QUERIES[@]}"; do
  START=$(date +%s%3N)
  RESULT=$("$QUAID_BIN" query "$QUERY" --db "$DB_PATH" --limit 5 --json 2>/dev/null || echo "")
  END=$(date +%s%3N)
  ELAPSED=$(( END - START ))
  SEM_LATENCY=$(( SEM_LATENCY + ELAPSED ))
  if [ "$(printf '%s' "$RESULT" | json_has_relevant_hit "$QUERY")" = "hit" ]; then
    SEM_PASS=$(( SEM_PASS + 1 ))
  fi
done
SEM_LATENCY=$(( SEM_LATENCY / ${#SEM_QUERIES[@]} ))
SEM_SCORE=$(( SEM_PASS * 8 ))  # ~8 pts per query
echo "Semantic: ${SEM_PASS}/${#SEM_QUERIES[@]} queries returned results, avg ${SEM_LATENCY}ms"

# Section 5: Performance
echo ""
echo "[5/8] Performance..."
PERF_SCORE=0
[ "$FTS_LATENCY" -lt 100 ] && PERF_SCORE=$(( PERF_SCORE + 10 ))
[ "$SEM_LATENCY" -lt 500 ] && PERF_SCORE=$(( PERF_SCORE + 10 ))
[ "$COLLECTION_ELAPSED" -lt 10000 ] && PERF_SCORE=$(( PERF_SCORE + 10 ))
echo "Performance score: $PERF_SCORE/30"

# Section 6: Integrity
echo ""
echo "[6/8] Integrity check..."
PAGE_COUNT=$("$QUAID_BIN" list --db "$DB_PATH" --limit 99999 --json 2>/dev/null | python3 -c "import json,sys; data=json.load(sys.stdin); print(len(data))" 2>/dev/null || echo "0")
if [ "$PAGE_COUNT" -gt 0 ]; then
  INTEGRITY_SCORE=20
  echo "Integrity: $PAGE_COUNT pages indexed"
else
  INTEGRITY_SCORE=0
  echo "Integrity: could not verify page count"
fi

# Section 7: Collections
echo ""
echo "[7/8] Collections check..."
if "$QUAID_BIN" collection list --db "$DB_PATH" 2>/dev/null | grep -q "docs"; then
  COLLECTIONS_SCORE=15
  echo "Collections: docs collection found"
else
  COLLECTIONS_SCORE=0
  echo "Collections: docs collection not found"
fi

# Section 8: MCP
echo ""
echo "[8/8] MCP server check..."
MCP_SCORE=0
if command -v "$QUAID_BIN" &>/dev/null; then
  # MCP stdio server: send a JSON-RPC initialize request, check for valid response
  MCP_REQUEST='{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"1.0"}}}'
  MCP_RESPONSE=$(echo "$MCP_REQUEST" | QUAID_DB="$DB_PATH" timeout 5 "$QUAID_BIN" serve 2>/dev/null || echo "")
  if echo "$MCP_RESPONSE" | grep -q '"result"'; then
    MCP_SCORE=20
    echo "MCP: server responded to initialize (20/20)"
  elif echo "$MCP_RESPONSE" | grep -q '"jsonrpc"'; then
    MCP_SCORE=10
    echo "MCP: server started and returned JSON-RPC (10/20)"
  else
    echo "MCP: no valid response (got: ${MCP_RESPONSE:0:100})"
  fi
fi

# Calculate total
TOTAL=$(( INSTALL_SCORE + IMPORT_SCORE + FTS_SCORE + SEM_SCORE + PERF_SCORE + INTEGRITY_SCORE + COLLECTIONS_SCORE + MCP_SCORE ))
MAX=215

echo ""
echo "=== DAB Results ==="
echo "Total: $TOTAL/$MAX ($(( TOTAL * 100 / MAX ))%)"

# Write JSON output
cat > "$OUTPUT" << JSONEOF
{
  "quaid_version": "${QUAID_VERSION}",
  "date": "${DATE}",
  "benchmark": "dab",
  "total_score": ${TOTAL},
  "max_score": ${MAX},
  "sections": {
    "install": {"score": ${INSTALL_SCORE}, "max": 10},
    "import": {"score": ${IMPORT_SCORE}, "max": 30},
    "fts": {"score": ${FTS_SCORE}, "max": 40},
    "semantic": {"score": ${SEM_SCORE}, "max": 50},
    "performance": {"score": ${PERF_SCORE}, "max": 30},
    "integrity": {"score": ${INTEGRITY_SCORE}, "max": 20},
    "collections": {"score": ${COLLECTIONS_SCORE}, "max": 15},
    "mcp": {"score": ${MCP_SCORE}, "max": 20}
  },
  "performance": {
    "fts_latency_ms": ${FTS_LATENCY},
    "semantic_latency_ms": ${SEM_LATENCY},
    "collection_add_ms": ${COLLECTION_ELAPSED}
  }
}
JSONEOF

echo "Results written to: $OUTPUT"
