#!/bin/bash
# MEMPALACE SEMANTIC SEARCH HELPER
# Search MemPalace for related information using semantic similarity
#
# Usage: ./mempal_semantic_search.sh "search query" [--wing wing_name] [--limit N]
#
# Examples:
#   ./mempal_semantic_search.sh "project structure"
#   ./mempal_semantic_search.sh "api authentication" --wing ananas-ai --limit 5

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MEMPALACE_SRC="$(dirname "$SCRIPT_DIR")"
PALACE_PATH="/home/zapostolski/.mempalace/palace"

# Check minimum arguments
if [[ $# -lt 1 ]]; then
    echo "Error: Search query is required"
    echo "Usage: $0 \"search query\" [--wing wing_name] [--limit N]"
    exit 1
fi

QUERY="$1"
shift

# Parse optional arguments
WING=""
LIMIT=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --wing)
            WING="$2"
            shift 2
            ;;
        --limit)
            LIMIT="$2"
            shift 2
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

# Create temporary Python script
TMP_PY=$(mktemp)
cat > "$TMP_PY" << EOF
import sys
sys.path.insert(0, '$MEMPALACE_SRC')
from mempalace.searcher import search_memories
import json

query = '$QUERY'
wing = '$WING' if '$WING' else None
limit = int('$LIMIT') if '$LIMIT'.isdigit() else 5

try:
    result = search_memories(
        query,
        palace_path='$PALACE_PATH',
        wing=wing,
        n_results=limit
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))
except Exception as e:
    print(json.dumps({'error': str(e)}, indent=2))
    sys.exit(1)
EOF

python3 "$TMP_PY"
EXIT_CODE=$?
rm -f "$TMP_PY"
exit $EXIT_CODE