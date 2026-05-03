#!/bin/bash
# MEMPALACE KNOWLEDGE ENRICHMENT HELPER
# Add structured facts to MemPalace knowledge graph for better querying
#
# Usage: ./mempal_enrich_knowledge.sh "subject" "predicate" "object" [--valid-from DATE] [--source-file FILE]
#
# Examples:
#   ./mempal_enrich_knowledge.sh "ananas-ai" "is_project_of" "ananas-platform" --valid-from "2026-01-01"
#   ./mempal_enrich_knowledge.sh "ai-marketing" "uses_mcp" "algolia" --source-file "~/projects/ai-marketing/algolia.ts"

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MEMPALACE_SRC="$(dirname "$SCRIPT_DIR")"

# Check minimum arguments
if [[ $# -lt 3 ]]; then
    echo "Error: Subject, predicate, and object are required"
    echo "Usage: $0 \"subject\" \"predicate\" \"object\" [--valid-from DATE] [--source-file FILE]"
    exit 1
fi

SUBJECT="$1"
PREDICATE="$2"
OBJECT="$3"
shift 3

# Parse optional arguments
VALID_FROM=""
SOURCE_FILE=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --valid-from)
            VALID_FROM="$2"
            shift 2
            ;;
        --source-file)
            SOURCE_FILE="$2"
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
from mempalace.knowledge_graph import KnowledgeGraph
import json
import os

subject = '$SUBJECT'
predicate = '$PREDICATE'
object = '$OBJECT'
valid_from = '$VALID_FROM' if '$VALID_FROM' else None
source_file = '$SOURCE_FILE' if '$SOURCE_FILE' else None

# Expand ~ in source_file
if source_file and source_file.startswith('~/'):
    source_file = os.path.expanduser(source_file)

try:
    kg = KnowledgeGraph()
    triple_id = kg.add_triple(subject, predicate, object,
                             valid_from=valid_from,
                             source_file=source_file)
    print(json.dumps({'success': True, 'triple_id': triple_id}, indent=2))
except Exception as e:
    print(json.dumps({'success': False, 'error': str(e)}, indent=2))
    sys.exit(1)
EOF

python3 "$TMP_PY"
EXIT_CODE=$?
rm -f "$TMP_PY"
exit $EXIT_CODE