#!/bin/bash
# MEMPALACE HOOK FOR OPENCODE
# Adapted from Claude Code hooks for use with OpenCode AI
#
# Install: Add to OpenCode's MCP config or create a custom command
# For OpenCode MCP integration, add to opencode.json:
# {
#   "mcp": {
#     "mempalace": {
#       "type": "local",
#       "command": "/home/zapostolski/.mempalace/src/hooks/mempal_opencode_hook.sh",
#       "args": ["stop"]
#     }
#   }
# }
#
# Or run manually: echo '{}' | ./mempal_opencode_hook.sh stop

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"
STATE_DIR="$HOME/.mempalace/hook_state"
SAVE_INTERVAL=10
SESSION_ID="opencode-$(date +%Y%m%d-%H%M%S)"

mkdir -p "$STATE_DIR"

log() {
    echo "[$(date '+%H:%M:%S')] $1" >> "$STATE_DIR/hook.log"
}

run_save() {
    log "OPENCODE SAVE TRIGGERED for session $SESSION_ID"
    
    # Output block reason to trigger save in OpenCode
    cat << 'HOOKJSON'
{
  "decision": "block",
  "reason": "AUTO-SAVE checkpoint. Save all new decisions, findings, milestones, blockers, architecture changes, code changes, and next steps from this session to your memory system. Be thorough - organize into wings/rooms. After saving, continue the conversation."
}
HOOKJSON
}

run_precompact() {
    log "OPENCODE PRE-COMPACT triggered"
    
    cat << 'HOOKJSON'
{
  "decision": "block",
  "reason": "COMPACTION IMMINENT. Save ALL topics, decisions, quotes, code, and context from this session to memory. After compaction detailed context will be lost. Save everything, then allow compaction."
}
HOOKJSON
}

handle_stop() {
    local since_last="${1:-0}"
    
    if [ "$since_last" -ge "$SAVE_INTERVAL" ]; then
        run_save
    else
        log "OpenCode: $since_last exchanges since last save (threshold: $SAVE_INTERVAL)"
        echo '{}'
    fi
}

increment_counter() {
    local counter_file="$STATE_DIR/opencode_counter"
    local count=0
    if [ -f "$counter_file" ]; then
        count=$(cat "$counter_file" 2>/dev/null || echo 0)
    fi
    count=$((count + 1))
    echo "$count" > "$counter_file"
    echo "$count"
}

main() {
    local hook_type="${1:-stop}"
    INPUT=$(cat)
    
    log "OpenCode hook triggered: $hook_type"
    
    case "$hook_type" in
        stop)
            local count
            count=$(increment_counter)
            handle_stop "$count"
            ;;
        precompact)
            run_precompact
            ;;
        *)
            log "Unknown hook type: $hook_type"
            echo '{}'
            ;;
    esac
}

main "$@"
