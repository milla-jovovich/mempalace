#!/bin/bash
# MEMPALACE KNOWLEDGE VERIFICATION HELPER
# Query MemPalace knowledge graph before making statements about projects/entities
#
# Usage: ./mempal_verify_knowledge.sh "entity name" [--type relationship_type] [--limit N]
#
# Examples:
#   ./mempal_verify_knowledge.sh "ananas-ai"
#   ./mempal_verify_knowledge.sh "ai-marketing" --type decision --limit 5
#   ./mempal_verify_knowledge.sh "project structure" --type assessment

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MEMPALACE_SRC="$(dirname "$SCRIPT_DIR")"

# Check minimum arguments
if [[ $# -lt 1 ]]; then
    echo "Error: Entity name is required"
    echo "Usage: $0 \"entity name\" [--type relationship_type] [--limit N]"
    exit 1
fi

ENTITY="$1"
shift

# Parse optional arguments
RELATIONSHIP_TYPE=""
LIMIT=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --type)
            RELATIONSHIP_TYPE="$2"
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
from mempalace.knowledge_graph import KnowledgeGraph
import json

entity = '$ENTITY'
rel_type = '$RELATIONSHIP_TYPE' if '$RELATIONSHIP_TYPE' else None
limit = int('$LIMIT') if '$LIMIT'.isdigit() else None

try:
    kg = KnowledgeGraph()
    results = kg.query_entity(entity)

    # Filter by relationship type if specified
    if rel_type:
        results = [r for r in results if r['predicate'] == rel_type]

    # Apply limit if specified
    if limit is not None:
        results = results[:limit]

    print(json.dumps(results, indent=2, ensure_ascii=False))
except Exception as e:
    print(json.dumps({'error': str(e)}, indent=2))
    sys.exit(1)
EOF

python3 "$TMP_PY"
EXIT_CODE=$?
rm -f "$TMP_PY"
exit $EXIT_CODE