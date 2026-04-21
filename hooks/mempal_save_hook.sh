#!/bin/bash
# MEMPALACE SAVE HOOK — Auto-save every N exchanges
#
# Claude Code "Stop" hook. After every assistant response:
# 1. Counts human messages in the session transcript
# 2. Every SAVE_INTERVAL messages, BLOCKS the AI from stopping
# 3. Returns a reason telling the AI to save structured diary + palace entries
# 4. AI does the save (topics, decisions, code, quotes → organized into palace)
# 5. Next Stop fires with stop_hook_active=true → lets AI stop normally
#
# The AI does the classification — it knows what wing/hall/closet to use
# because it has context about the conversation. No regex needed.
#
# === INSTALL ===
# Add to .claude/settings.local.json:
#
#   "hooks": {
#     "Stop": [{
#       "matcher": "*",
#       "hooks": [{
#         "type": "command",
#         "command": "/absolute/path/to/mempal_save_hook.sh",
#         "timeout": 30
#       }]
#     }]
#   }
#
# For Codex CLI, add to .codex/hooks.json:
#
#   "Stop": [{
#     "type": "command",
#     "command": "/absolute/path/to/mempal_save_hook.sh",
#     "timeout": 30
#   }]
#
# === HOW IT WORKS ===
#
# Claude Code sends JSON on stdin with these fields:
#   session_id       — unique session identifier
#   stop_hook_active — true if AI is already in a save cycle (prevents infinite loop)
#   transcript_path  — path to the JSONL transcript file
#
# When we block, Claude Code shows our "reason" to the AI as a system message.
# The AI then saves to memory, and when it tries to stop again,
# stop_hook_active=true so we let it through. No infinite loop.
#
# === MEMPALACE CLI ===
# This repo uses: mempalace mine <dir>
# or:            mempalace mine <dir> --mode convos
# Set MEMPAL_DIR below if you want the hook to auto-ingest after blocking.
# Leave blank to rely on the AI's own save instructions.
#
# === CONFIGURATION ===

SAVE_INTERVAL=15  # Save every N human messages (adjust to taste)
STATE_DIR="$HOME/.mempalace/hook_state"
mkdir -p "$STATE_DIR"

# Optional: set to the directory you want auto-ingested on each save trigger.
# Example: MEMPAL_DIR="$HOME/conversations"
# Leave empty to skip auto-ingest (AI handles saving via the block reason).
MEMPAL_DIR=""

# Resolve the Python interpreter the hook should use.
#
# Why this is nontrivial: GUI-launched Claude Code on macOS (or any harness
# that doesn't inherit the user's shell PATH) may find a `python3` on PATH
# that lacks mempalace — e.g. /usr/bin/python3 while the user installed
# mempalace into a venv or pyenv. Users in that situation can point the
# hook at the right interpreter by exporting MEMPAL_PYTHON.
#
# Resolution order (first hit wins):
#   1. $MEMPAL_PYTHON          — explicit user override (absolute path)
#   2. $(command -v python3)   — first python3 on the hook's PATH
#   3. bare "python3"          — last-resort fallback (hope the PATH has it)
MEMPAL_PYTHON_BIN="${MEMPAL_PYTHON:-}"
if [ -z "$MEMPAL_PYTHON_BIN" ] || [ ! -x "$MEMPAL_PYTHON_BIN" ]; then
    MEMPAL_PYTHON_BIN="$(command -v python3 2>/dev/null || echo python3)"
fi

# Read JSON input from stdin
INPUT=$(cat)

# Parse all fields in a single Python call (3x faster than separate invocations)
# SECURITY: All values are sanitized before being interpolated into shell assignments.
# stop_hook_active is coerced to a strict True/False to prevent command injection via eval.
eval $(echo "$INPUT" | "$MEMPAL_PYTHON_BIN" -c "
import sys, json, re
data = json.load(sys.stdin)
sid = data.get('session_id', 'unknown')
sha_raw = data.get('stop_hook_active', False)
tp = data.get('transcript_path', '')
# Shell-safe output — only allow alphanumeric, underscore, hyphen, slash, dot, tilde
safe = lambda s: re.sub(r'[^a-zA-Z0-9_/.\-~]', '', str(s))
# Coerce stop_hook_active to strict boolean string
sha = 'True' if sha_raw is True or str(sha_raw).lower() in ('true', '1', 'yes') else 'False'
print(f'SESSION_ID=\"{safe(sid)}\"')
print(f'STOP_HOOK_ACTIVE=\"{sha}\"')
print(f'TRANSCRIPT_PATH=\"{safe(tp)}\"')
" 2>/dev/null)

# Expand ~ in path
TRANSCRIPT_PATH="${TRANSCRIPT_PATH/#\~/$HOME}"

# If we're already in a save cycle, let the AI stop normally
# This is the infinite-loop prevention: block once → AI saves → tries to stop again → we let it through
if [ "$STOP_HOOK_ACTIVE" = "True" ] || [ "$STOP_HOOK_ACTIVE" = "true" ]; then
    echo "{}"
    exit 0
fi

# Count human messages in the JSONL transcript
# SECURITY: Pass transcript path as sys.argv to avoid shell injection via crafted paths
if [ -f "$TRANSCRIPT_PATH" ]; then
    EXCHANGE_COUNT=$("$MEMPAL_PYTHON_BIN" - "$TRANSCRIPT_PATH" <<'PYEOF'
import json, sys
count = 0
with open(sys.argv[1]) as f:
    for line in f:
        try:
            entry = json.loads(line)
            msg = entry.get('message', {})
            if isinstance(msg, dict) and msg.get('role') == 'user':
                content = msg.get('content', '')
                if isinstance(content, str) and '<command-message>' in content:
                    continue
                count += 1
        except:
            pass
print(count)
PYEOF
2>/dev/null)
else
    EXCHANGE_COUNT=0
fi

# Track last save point for this session
LAST_SAVE_FILE="$STATE_DIR/${SESSION_ID}_last_save"
LAST_SAVE=0
if [ -f "$LAST_SAVE_FILE" ]; then
    LAST_SAVE_RAW=$(cat "$LAST_SAVE_FILE")
    # SECURITY: Validate as plain integer before arithmetic to prevent command injection
    if [[ "$LAST_SAVE_RAW" =~ ^[0-9]+$ ]]; then
        LAST_SAVE="$LAST_SAVE_RAW"
    fi
fi

SINCE_LAST=$((EXCHANGE_COUNT - LAST_SAVE))

# Log for debugging (check ~/.mempalace/hook_state/hook.log)
echo "[$(date '+%H:%M:%S')] Session $SESSION_ID: $EXCHANGE_COUNT exchanges, $SINCE_LAST since last save" >> "$STATE_DIR/hook.log"

# Time to save?
if [ "$SINCE_LAST" -ge "$SAVE_INTERVAL" ] && [ "$EXCHANGE_COUNT" -gt 0 ]; then
    # Update last save point
    echo "$EXCHANGE_COUNT" > "$LAST_SAVE_FILE"

    echo "[$(date '+%H:%M:%S')] TRIGGERING SAVE at exchange $EXCHANGE_COUNT" >> "$STATE_DIR/hook.log"

    # Auto-mine the transcript. Two paths:
    # 1. TRANSCRIPT_PATH (from Claude Code) — mine the directory it lives in
    # 2. MEMPAL_DIR (user-configured) — mine that directory
    # At least one should work. If neither is set, nothing mines.
    MINE_DIR=""
    if [ -n "$TRANSCRIPT_PATH" ] && [ -f "$TRANSCRIPT_PATH" ]; then
        MINE_DIR="$(dirname "$TRANSCRIPT_PATH")"
    fi
    if [ -n "$MEMPAL_DIR" ] && [ -d "$MEMPAL_DIR" ]; then
        MINE_DIR="$MEMPAL_DIR"
    fi
    if [ -n "$MINE_DIR" ]; then
        mempalace mine "$MINE_DIR" >> "$STATE_DIR/hook.log" 2>&1 &
    fi

    # MEMPAL_VERBOSE toggle:
    #   true  = developer mode — block and show diaries/code in chat
    #   false = silent mode (default) — save in background, no chat clutter
    # Set via: export MEMPAL_VERBOSE=true
    if [ "$MEMPAL_VERBOSE" = "true" ] || [ "$MEMPAL_VERBOSE" = "1" ]; then
        cat << 'HOOKJSON'
{
  "decision": "block",
  "reason": "MemPalace save checkpoint. Write a brief session diary entry covering key topics, decisions, and code changes since the last save. Use verbatim quotes where possible. Continue after saving."
}
HOOKJSON
    else
        # Silent mode: return empty JSON to not block. "decision": "allow" is
        # not a valid value — only "block" or {} are recognized.
        echo '{}'
    fi
else
    # Not time yet — let the AI stop normally
    echo "{}"
fi
