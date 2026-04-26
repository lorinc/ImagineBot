#!/usr/bin/env bash
# Pipeline integrity check — run after any pipeline rebuild.
# Exits 0 on pass, 1 on first failure.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
AI_CLEANED="$REPO_ROOT/data/pipeline/latest/02_ai_cleaned"
CHUNKED="$REPO_ROOT/data/pipeline/latest/03_chunked"
MULTI_INDEX="$REPO_ROOT/data/index/multi_index.json"

PASS=0
FAIL=0

check() {
  local label="$1"; local result="$2"; local detail="$3"
  if [ "$result" = "ok" ]; then
    echo "  ✓  $label"
    PASS=$((PASS+1))
  else
    echo "  ✗  $label — $detail"
    FAIL=$((FAIL+1))
  fi
}

echo "Pipeline integrity check"
echo "========================"

# 1. 02_ai_cleaned is non-empty
md_count=$(find "$AI_CLEANED" -name "*.md" | wc -l)
if [ "$md_count" -gt 0 ]; then
  check "02_ai_cleaned non-empty ($md_count files)" "ok" ""
else
  check "02_ai_cleaned non-empty" "fail" "directory is empty or missing"
fi

# 2. Every indexed source basename exists in 02_ai_cleaned
missing=$(python3 -c "
import json, os
mi = json.load(open('$MULTI_INDEX'))
missing = [os.path.basename(d['source']) for d in mi['documents'] if not os.path.exists(os.path.join('$AI_CLEANED', os.path.basename(d['source'])))]
print('\n'.join(missing))
")

if [ -z "$missing" ]; then
  check "All indexed sources present in 02_ai_cleaned" "ok" ""
else
  check "All indexed sources present in 02_ai_cleaned" "fail" "missing: $missing"
fi

# 3. multi_index.json has at least 10 nodes (sanity floor)
node_count=$(python3 -c "
import json
d = json.load(open('$MULTI_INDEX'))
print(sum(doc.get('node_count', 0) for doc in d['documents']))
")

if [ "$node_count" -ge 10 ]; then
  check "multi_index.json node count >= 10 (got $node_count)" "ok" ""
else
  check "multi_index.json node count >= 10" "fail" "got $node_count"
fi

# 4. Step 4 ran: at least one *_prose.md present in 03_chunked
prose_count=$(find "$CHUNKED" -name "*_prose.md" | wc -l)
if [ "$prose_count" -gt 0 ]; then
  check "Step 4 prose files present in 03_chunked ($prose_count files)" "ok" ""
else
  check "Step 4 prose files present in 03_chunked" "fail" "no *_prose.md files found — step 4 may not have run"
fi

echo ""
echo "Result: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
