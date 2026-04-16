"""
Hook logic for MemPalace — Python implementation of session-start, stop, and precompact hooks.

Reads JSON from stdin, outputs JSON to stdout.
Supported hooks: session-start, stop, precompact
Supported harnesses: claude-code, codex (extensible to cursor, gemini, etc.)
"""

import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from .config import MempalaceConfig

SAVE_INTERVAL = 15
STATE_DIR = Path.home() / ".mempalace" / "hook_state"

STOP_BLOCK_REASON = (
    "AUTO-SAVE checkpoint (MemPalace). First check whether MemPalace MCP tools are available in this session.\n"
    "If tools like mempalace_diary_write, mempalace_add_drawer, or mempalace_kg_add are available, use them to save this session's key content.\n"
    "If those MCP tools are NOT available, do not invent CLI substitutes and do not run shell commands like mempalace_diary_write or mempalace_add_drawer. Those are MCP tool names, not CLI commands.\n"
    "In that case, briefly note that MemPalace auto-save is unavailable in this session and continue normally.\n"
    "Do NOT write to Claude Code's native auto-memory (.md files)."
)

PRECOMPACT_BLOCK_REASON = (
    "COMPACTION IMMINENT (MemPalace). First check whether MemPalace MCP tools are available in this session.\n"
    "If tools like mempalace_diary_write, mempalace_add_drawer, or mempalace_kg_add are available, use them to save ALL important session content before context is lost.\n"
    "If those MCP tools are NOT available, do not invent CLI substitutes and do not run shell commands like mempalace_diary_write or mempalace_add_drawer. Those are MCP tool names, not CLI commands.\n"
    "In that case, briefly note that MemPalace auto-save is unavailable in this session, avoid fake saves, and let compaction proceed.\n"
    "Do NOT write to Claude Code's native auto-memory (.md files)."
)


def _sanitize_session_id(session_id: str) -> str:
    """Only allow alnum, dash, underscore to prevent path traversal."""
    sanitized = re.sub(r"[^a-zA-Z0-9_-]", "", session_id)
    return sanitized or "unknown"


def _count_human_messages(transcript_path: str) -> int:
    """Count human messages in a JSONL transcript, skipping command-messages."""
    path = Path(transcript_path).expanduser()
    if not path.is_file():
        return 0
    count = 0
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                try:
                    entry = json.loads(line)
                    msg = entry.get("message", {})
                    if isinstance(msg, dict) and msg.get("role") == "user":
                        content = msg.get("content", "")
                        if isinstance(content, str):
                            if "<command-message>" in content:
                                continue
                        elif isinstance(content, list):
                            text = " ".join(
                                b.get("text", "") for b in content if isinstance(b, dict)
                            )
                            if "<command-message>" in text:
                                continue
                        count += 1
                    # Also handle Codex CLI transcript format
                    # {"type": "event_msg", "payload": {"type": "user_message", "message": "..."}}
                    elif entry.get("type") == "event_msg":
                        payload = entry.get("payload", {})
                        if isinstance(payload, dict) and payload.get("type") == "user_message":
                            msg_text = payload.get("message", "")
                            if isinstance(msg_text, str) and "<command-message>" not in msg_text:
                                count += 1
                except (json.JSONDecodeError, AttributeError):
                    pass
    except OSError:
        return 0
    return count


def _log(message: str):
    """Append to hook state log file."""
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        log_path = STATE_DIR / "hook.log"
        timestamp = datetime.now().strftime("%H:%M:%S")
        with open(log_path, "a") as f:
            f.write(f"[{timestamp}] {message}\n")
    except OSError:
        pass


def _silent_save_enabled() -> bool:
    """Whether hooks should save directly instead of blocking for MCP calls."""
    try:
        return MempalaceConfig().hook_silent_save
    except Exception:
        return True


def _transcript_excerpt(transcript_path: str, max_chars: int = 6000) -> str:
    """Return a normalized tail excerpt from the transcript for direct checkpointing."""
    if not transcript_path:
        return ""

    try:
        from .normalize import normalize

        text = normalize(transcript_path)
    except Exception:
        try:
            text = Path(transcript_path).expanduser().read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""

    text = text.strip()
    if not text:
        return ""
    if len(text) <= max_chars:
        return text
    return "...\n" + text[-max_chars:]


def _write_checkpoint_ack(exchange_count: int, hook_name: str, result: dict):
    """Write a short ack file so clients can notice a silent save happened."""
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        ack_file = STATE_DIR / "last_checkpoint"
        payload = {
            "ts": datetime.now().isoformat(),
            "msgs": exchange_count,
            "hook": hook_name,
            "entry_id": result.get("entry_id"),
        }
        ack_file.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def _silent_checkpoint(
    session_id: str,
    transcript_path: str,
    exchange_count: int,
    hook_name: str,
    harness: str,
) -> bool:
    """Persist a lightweight diary checkpoint directly from the hook runtime."""
    excerpt = _transcript_excerpt(transcript_path)
    if not excerpt:
        excerpt = "(No transcript excerpt available.)"

    agent_name = harness.replace("-", "_")
    topic = f"{agent_name}_autosave"

    entry = (
        f"Harness: {harness}\n"
        f"Session: {session_id}\n"
        f"Hook: {hook_name}\n"
        f"Human messages: {exchange_count}\n"
        f"Timestamp: {datetime.now().isoformat()}\n\n"
        f"Transcript excerpt:\n{excerpt}"
    )

    try:
        from .mcp_server import tool_diary_write

        result = tool_diary_write(
            agent_name=agent_name,
            entry=entry,
            topic=topic,
        )
    except Exception as e:
        _log(f"silent checkpoint failed during {hook_name}: {e}")
        return False

    if result.get("success"):
        _write_checkpoint_ack(exchange_count, hook_name, result)
        _log(f"silent checkpoint saved during {hook_name}: {result.get('entry_id', 'unknown')}")
        return True

    _log(f"silent checkpoint failed during {hook_name}: {result}")
    return False


def _output(data: dict):
    """Print JSON to stdout with consistent formatting (pretty-printed)."""
    print(json.dumps(data, indent=2, ensure_ascii=False))


def _maybe_auto_ingest():
    """If MEMPAL_DIR is set and exists, run mempalace mine in background."""
    mempal_dir = os.environ.get("MEMPAL_DIR", "")
    if mempal_dir and os.path.isdir(mempal_dir):
        try:
            log_path = STATE_DIR / "hook.log"
            with open(log_path, "a") as log_f:
                subprocess.Popen(
                    [sys.executable, "-m", "mempalace", "mine", mempal_dir],
                    stdout=log_f,
                    stderr=log_f,
                )
        except OSError:
            pass


SUPPORTED_HARNESSES = {"claude-code", "codex"}


def _parse_harness_input(data: dict, harness: str) -> dict:
    """Parse stdin JSON according to the harness type."""
    if harness not in SUPPORTED_HARNESSES:
        print(f"Unknown harness: {harness}", file=sys.stderr)
        sys.exit(1)
    return {
        "session_id": _sanitize_session_id(str(data.get("session_id", "unknown"))),
        "stop_hook_active": data.get("stop_hook_active", False),
        "transcript_path": str(data.get("transcript_path", "")),
    }


def hook_stop(data: dict, harness: str):
    """Stop hook: block every N messages for auto-save."""
    parsed = _parse_harness_input(data, harness)
    session_id = parsed["session_id"]
    stop_hook_active = parsed["stop_hook_active"]
    transcript_path = parsed["transcript_path"]

    # If already in a save cycle, let through (infinite-loop prevention)
    if str(stop_hook_active).lower() in ("true", "1", "yes"):
        _output({})
        return

    # Count human messages
    exchange_count = _count_human_messages(transcript_path)

    # Track last save point
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    last_save_file = STATE_DIR / f"{session_id}_last_save"
    last_save = 0
    if last_save_file.is_file():
        try:
            last_save = int(last_save_file.read_text().strip())
        except (ValueError, OSError):
            last_save = 0

    since_last = exchange_count - last_save

    _log(f"Session {session_id}: {exchange_count} exchanges, {since_last} since last save")

    if since_last >= SAVE_INTERVAL and exchange_count > 0:
        # Update last save point
        try:
            last_save_file.write_text(str(exchange_count), encoding="utf-8")
        except OSError:
            pass

        _log(f"TRIGGERING SAVE at exchange {exchange_count}")

        # Optional: auto-ingest if MEMPAL_DIR is set
        _maybe_auto_ingest()

        if _silent_save_enabled():
            if _silent_checkpoint(session_id, transcript_path, exchange_count, "stop", harness):
                _output({})
                return
            _log("silent save failed, falling back to legacy MCP block")

        _output({"decision": "block", "reason": STOP_BLOCK_REASON})
    else:
        _output({})


def hook_session_start(data: dict, harness: str):
    """Session start hook: initialize session tracking state."""
    parsed = _parse_harness_input(data, harness)
    session_id = parsed["session_id"]

    _log(f"SESSION START for session {session_id}")

    # Initialize session state directory
    STATE_DIR.mkdir(parents=True, exist_ok=True)

    # Pass through — no blocking on session start
    _output({})


def hook_precompact(data: dict, harness: str):
    """Precompact hook: save directly when silent-save is enabled, else block for MCP."""
    parsed = _parse_harness_input(data, harness)
    session_id = parsed["session_id"]
    transcript_path = parsed["transcript_path"]
    exchange_count = _count_human_messages(transcript_path)

    _log(f"PRE-COMPACT triggered for session {session_id}")

    # Optional: auto-ingest synchronously before compaction (so memories land first)
    mempal_dir = os.environ.get("MEMPAL_DIR", "")
    if mempal_dir and os.path.isdir(mempal_dir):
        try:
            log_path = STATE_DIR / "hook.log"
            with open(log_path, "a") as log_f:
                subprocess.run(
                    [sys.executable, "-m", "mempalace", "mine", mempal_dir],
                    stdout=log_f,
                    stderr=log_f,
                    timeout=60,
                )
        except OSError:
            pass

    if _silent_save_enabled():
        if _silent_checkpoint(session_id, transcript_path, exchange_count, "precompact", harness):
            _output({})
            return
        _log("silent precompact save failed, falling back to legacy MCP block")

    # Legacy fallback: block so Claude can attempt MCP-based persistence
    _output({"decision": "block", "reason": PRECOMPACT_BLOCK_REASON})


def run_hook(hook_name: str, harness: str):
    """Main entry point: read stdin JSON, dispatch to hook handler."""
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError):
        _log("WARNING: Failed to parse stdin JSON, proceeding with empty data")
        data = {}

    hooks = {
        "session-start": hook_session_start,
        "stop": hook_stop,
        "precompact": hook_precompact,
    }

    handler = hooks.get(hook_name)
    if handler is None:
        print(f"Unknown hook: {hook_name}", file=sys.stderr)
        sys.exit(1)

    handler(data, harness)
