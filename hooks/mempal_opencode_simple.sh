#!/bin/bash
# MEMPALACE OPENCODE HOOK (No Python dependencies required)
# This hook logs checkpoints and can be run alongside mempalace's Codex/Claude hooks
#
# Usage: 
#   1. Run manually after important sessions: ./mempal_opencode_simple.sh save
#   2. Or integrate via OpenCode custom commands
#
# This creates checkpoint files that can be mined later by mempalace

set -euo pipefail

STATE_DIR="$HOME/.mempalace/hook_state"
CHECKPOINT_DIR="$STATE_DIR/opencode_checkpoints"
SESSION_ID="opencode-$(date +%Y%m%d-%H%M%S)"
TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')

mkdir -p "$STATE_DIR" "$CHECKPOINT_DIR"

log() {
    echo "[$(date '+%H:%M:%S')] OPENCODE: $1" >> "$STATE_DIR/hook.log"
}

create_checkpoint() {
    local checkpoint_file="$CHECKPOINT_DIR/${SESSION_ID}.md"
    local notes="${1:-}"
    
    log "Creating checkpoint: $SESSION_ID"
    
    cat > "$checkpoint_file" << EOF
# OpenCode Session Checkpoint

**Session:** $SESSION_ID  
**Timestamp:** $TIMESTAMP  
**User:** Zharko Apostolski

## Session Notes
$notes

## Key Topics Discussed

## Decisions Made

## Code Changes

## Next Steps

---
*Created by mempalace OpenCode hook*
EOF
    
    echo "Checkpoint saved: $checkpoint_file"
    log "Checkpoint created: $checkpoint_file"
}

main() {
    local command="${1:-save}"
    
    case "$command" in
        save)
            log "Save command received"
            create_checkpoint "Manual checkpoint from OpenCode session"
            ;;
        status)
            log "Status check"
            echo "OpenCode mempalace hook status:"
            echo "  Checkpoints: $(ls -1 "$CHECKPOINT_DIR" 2>/dev/null | wc -l)"
            echo "  Last: $(ls -t "$CHECKPOINT_DIR" 2>/dev/null | head -1)"
            ;;
        *)
            echo "Usage: $0 {save|status}"
            exit 1
            ;;
    esac
}

main "$@"
