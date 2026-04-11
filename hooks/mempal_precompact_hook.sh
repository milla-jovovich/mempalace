#!/bin/bash
# MEMPALACE PRE-COMPACT HOOK — Emergency save before compaction
#
# Claude Code "PreCompact" hook. Fires RIGHT BEFORE the conversation
# gets compressed to free up context window space.
#
# This is the safety net. When compaction happens, the AI loses detailed
# context about what was discussed. This hook forces one final save of
# EVERYTHING before that happens.
#
# Unlike the save hook (which triggers every N exchanges), this ALWAYS
# blocks — because compaction is always worth saving before.
#
# === INSTALL ===
# Add to .claude/settings.local.json:
#
#   "hooks": {
#     "PreCompact": [{
#       "hooks": [{
#         "type": "command",
#         "command": "/absolute/path/to/mempal_precompact_hook.sh",
#         "timeout": 30
#       }]
#     }]
#   }
#
# For Codex CLI, add to .codex/hooks.json:
#
#   "PreCompact": [{
#     "type": "command",
#     "command": "/absolute/path/to/mempal_precompact_hook.sh",
#     "timeout": 30
#   }]
#
# === HOW IT WORKS ===
#
# Claude Code sends JSON on stdin with:
#   session_id — unique session identifier
#
# We always return decision: "block" with a reason telling the AI
# to save everything. After the AI saves, compaction proceeds normally.
#
# === MEMPALACE CLI ===
# This repo uses: mempalace mine <dir>
# or:            mempalace mine <dir> --mode convos
# Set MEMPAL_DIR below if you want the hook to auto-ingest before compaction.
# Leave blank to rely on the AI's own save instructions.

STATE_DIR="$HOME/.mempalace/hook_state"
mkdir -p "$STATE_DIR"

# Optional: set to the directory you want auto-ingested before compaction.
# Example: MEMPAL_DIR="$HOME/conversations"
# Leave empty to skip auto-ingest (AI handles saving via the block reason).
MEMPAL_DIR=""

# Python interpreter with mempalace + chromadb installed.
# Auto-detects: MEMPALACE_PYTHON env var → repo venv → system python3
if [ -n "$MEMPALACE_PYTHON" ]; then
    MP_PYTHON="$MEMPALACE_PYTHON"
elif [ -f "$(dirname "$(dirname "${BASH_SOURCE[0]}")")/venv/bin/python3" ]; then
    MP_PYTHON="$(dirname "$(dirname "${BASH_SOURCE[0]}")")/venv/bin/python3"
else
    MP_PYTHON="python3"
fi

# Read JSON input from stdin
INPUT=$(cat)

SESSION_ID=$(echo "$INPUT" | python3 -c "
import sys, json, re
data = json.load(sys.stdin)
sid = data.get('session_id', 'unknown')
safe = lambda s: re.sub(r'[^a-zA-Z0-9_/.\-~]', '', str(s))
print(safe(sid))
" 2>/dev/null)

echo "[$(date '+%H:%M:%S')] PRE-COMPACT triggered for session $SESSION_ID" >> "$STATE_DIR/hook.log"

# Also parse transcript_path if present in the input
TRANSCRIPT_PATH=$(echo "$INPUT" | python3 -c "
import sys, json, re
data = json.load(sys.stdin)
tp = data.get('transcript_path', '')
safe = lambda s: re.sub(r'[^a-zA-Z0-9_/.\-~]', '', str(s))
print(safe(tp))
" 2>/dev/null)
TRANSCRIPT_PATH="${TRANSCRIPT_PATH/#\~/$HOME}"

# If no transcript_path in input, find it by session_id
if [ -z "$TRANSCRIPT_PATH" ] || [ ! -f "$TRANSCRIPT_PATH" ]; then
    if [ -n "$SESSION_ID" ] && [ "$SESSION_ID" != "unknown" ]; then
        FOUND=$(find "$HOME/.claude/projects" -name "${SESSION_ID}.jsonl" -type f 2>/dev/null | head -1)
        if [ -n "$FOUND" ]; then
            TRANSCRIPT_PATH="$FOUND"
        fi
    fi
fi

# Auto-mine the transcript — captures tool output before compaction loses it
if [ -f "$TRANSCRIPT_PATH" ]; then
    echo "[$(date '+%H:%M:%S')] Mining transcript: $TRANSCRIPT_PATH" >> "$STATE_DIR/hook.log"
    "$MP_PYTHON" - "$TRANSCRIPT_PATH" <<'PYMINE'
import sys
try:
    import hashlib
    from datetime import datetime
    from mempalace.normalize import normalize
    from mempalace.convo_miner import chunk_exchanges, detect_convo_room
    from mempalace.palace import get_collection
    from mempalace.config import MempalaceConfig
    palace = MempalaceConfig().palace_path
    content = normalize(sys.argv[1])
    if content and len(content.strip()) >= 50:
        collection = get_collection(palace)
        source = sys.argv[1]
        # No file_already_mined check — transcript grows during session.
        # upsert is idempotent: same chunk_index → same ID → overwrite.
        chunks = chunk_exchanges(content)
        if chunks:
            room = detect_convo_room(content) or "session"
            wing = "conversations"
            docs, ids, metas = [], [], []
            for chunk in chunks:
                cid = hashlib.sha256(
                    (source + str(chunk["chunk_index"])).encode()
                ).hexdigest()[:24]
                docs.append(chunk["content"])
                ids.append(f"drawer_{wing}_{room}_{cid}")
                metas.append({
                    "wing": wing, "room": room, "source_file": source,
                    "chunk_index": chunk["chunk_index"],
                    "added_by": "hook", "filed_at": datetime.now().isoformat(),
                    "ingest_mode": "convos", "extract_mode": "exchange",
                })
            for i in range(0, len(docs), 100):
                collection.upsert(
                    documents=docs[i:i+100], ids=ids[i:i+100],
                    metadatas=metas[i:i+100],
                )
except Exception:
    pass  # Hook must never crash the AI
PYMINE
    >> "$STATE_DIR/hook.log" 2>&1
fi

# Optional: run mempalace ingest synchronously so memories land before compaction
if [ -n "$MEMPAL_DIR" ] && [ -d "$MEMPAL_DIR" ]; then
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    REPO_DIR="$(dirname "$SCRIPT_DIR")"
    "$MP_PYTHON" -m mempalace mine "$MEMPAL_DIR" >> "$STATE_DIR/hook.log" 2>&1
fi

# Always block — compaction = save everything
cat << 'HOOKJSON'
{
  "decision": "block",
  "reason": "COMPACTION IMMINENT — MEMPALACE SAVE REQUIRED. Use the mempalace MCP tools (mempalace_add_drawer, mempalace_diary_write) to save EVERYTHING to the memory palace. Do NOT save to your internal Claude memory (~/.claude/projects/.../memory/) — save to the MEMPALACE via MCP tools only. CRITICAL: Save tool output VERBATIM — Bash command results, probe findings, search results, build output, error messages. These are lost on compaction and exist nowhere else. Also save all topics, decisions, quotes, code, and important context. Be thorough — after compaction, detailed context will be lost. Organize into appropriate wings/rooms. Save everything, then allow compaction to proceed."
}
HOOKJSON
