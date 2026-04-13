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

SAVE_INTERVAL = 15
STATE_DIR = Path.home() / ".mempalace" / "hook_state"

STOP_BLOCK_REASON = (
    "AUTO-SAVE checkpoint. Save key topics, decisions, quotes, and code "
    "from this session to your memory system. Organize into appropriate "
    "categories. Use verbatim quotes where possible. Continue conversation "
    "after saving."
)

PRECOMPACT_BLOCK_REASON = (
    "COMPACTION IMMINENT. Save ALL topics, decisions, quotes, code, and "
    "important context from this session to your memory system. Be thorough "
    "\u2014 after compaction, detailed context will be lost. Organize into "
    "appropriate categories. Use verbatim quotes where possible. Save "
    "everything, then allow compaction to proceed."
)


def _auto_ingest_pid_file() -> Path:
    """Return the pid file used to debounce background mining.

    Hooks can fire repeatedly while one `mempalace mine` is still running. A
    small pid file is enough to make the auto-ingest path single-flight without
    introducing new dependencies or a long-lived daemon.
    """
    return STATE_DIR / "auto_ingest.pid"


def _sanitize_session_id(session_id: str) -> str:
    """Only allow alnum, dash, underscore to prevent path traversal."""
    sanitized = re.sub(r"[^a-zA-Z0-9_-]", "", session_id)
    return sanitized or "unknown"


def _extract_text_content(content) -> str:
    """Extract user-authored text from a hook transcript content payload.

    The hook save cadence should advance on actual human turns, not on tool
    plumbing. We therefore ignore non-text blocks here even though the full
    transcript normalizer retains them for richer mining.
    """
    if isinstance(content, str):
        return content.strip()
    if not isinstance(content, list):
        return ""

    parts = []
    for block in content:
        if isinstance(block, str):
            parts.append(block)
        elif isinstance(block, dict) and block.get("type") == "text":
            parts.append(str(block.get("text", "")))
    return "\n".join(part for part in parts if part).strip()


def _is_tool_result_only(content) -> bool:
    """Return True for Claude Code synthetic turns that only carry tool output.

    Claude Code records tool_result blocks as human messages so the session
    transcript can represent the tool loop. Those entries are not fresh user
    intent and should not push MemPalace closer to an auto-save checkpoint.
    """
    return (
        isinstance(content, list)
        and bool(content)
        and all(isinstance(block, dict) and block.get("type") == "tool_result" for block in content)
    )


def _is_real_human_turn(entry: dict) -> bool:
    """Recognize countable human turns across supported raw hook transcripts.

    Hooks receive the harness-native JSONL transcript, not the normalized
    MemPalace transcript. This helper keeps the stop-hook threshold aligned with
    the actual conversation across both Claude Code and Codex logs.
    """
    if not isinstance(entry, dict):
        return False

    # Codex stores canonical user turns as event_msg payloads.
    if entry.get("type") == "event_msg":
        payload = entry.get("payload", {})
        if not isinstance(payload, dict) or payload.get("type") != "user_message":
            return False
        msg_text = payload.get("message", "")
        return isinstance(msg_text, str) and bool(msg_text.strip()) and "<command-message>" not in msg_text

    message = entry.get("message", {})
    if not isinstance(message, dict):
        return False

    entry_type = entry.get("type", "")
    role = message.get("role", "")
    if entry_type not in ("human", "user") and role != "user":
        return False

    content = message.get("content", "")
    if _is_tool_result_only(content):
        return False

    text = _extract_text_content(content)
    return bool(text) and "<command-message>" not in text


def _count_human_messages(transcript_path: str) -> int:
    """Count human messages in a JSONL transcript, skipping harness noise."""
    path = Path(transcript_path).expanduser()
    if not path.is_file():
        return 0
    count = 0
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                try:
                    entry = json.loads(line)
                    if _is_real_human_turn(entry):
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


def _output(data: dict):
    """Print JSON to stdout with consistent formatting (pretty-printed)."""
    print(json.dumps(data, indent=2, ensure_ascii=False))


def _active_auto_ingest_pid() -> int | None:
    """Return the active auto-ingest pid, clearing stale pid files on sight."""
    pid_file = _auto_ingest_pid_file()
    if not pid_file.is_file():
        return None

    try:
        pid = int(pid_file.read_text(encoding="utf-8").strip())
    except (ValueError, OSError):
        pid_file.unlink(missing_ok=True)
        return None

    try:
        os.kill(pid, 0)
        return pid
    except ProcessLookupError:
        pid_file.unlink(missing_ok=True)
        return None
    except PermissionError:
        # Treat permission failures as "still running" so we do not start a
        # second miner against the same palace when process ownership differs.
        return pid
    except OSError:
        pid_file.unlink(missing_ok=True)
        return None


def _write_auto_ingest_pid(pid: int):
    """Persist the pid of the active auto-ingest process."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    _auto_ingest_pid_file().write_text(str(pid), encoding="utf-8")


def _clear_auto_ingest_pid(pid: int | None = None):
    """Remove the pid file once the matching ingest process is finished.

    The optional pid guard prevents one older cleanup path from deleting the
    marker for a newer process that started after a race or retry.
    """
    pid_file = _auto_ingest_pid_file()
    if not pid_file.is_file():
        return
    if pid is not None:
        try:
            recorded = int(pid_file.read_text(encoding="utf-8").strip())
        except (ValueError, OSError):
            pid_file.unlink(missing_ok=True)
            return
        if recorded != pid:
            return
    pid_file.unlink(missing_ok=True)


def _spawn_auto_ingest(log_f):
    """Start `mempalace mine` if one is not already running."""
    mempal_dir = os.environ.get("MEMPAL_DIR", "")
    if not mempal_dir or not os.path.isdir(mempal_dir):
        return None

    active_pid = _active_auto_ingest_pid()
    if active_pid is not None:
        _log(f"Auto-ingest already running (pid {active_pid}); skipping new spawn")
        return None

    proc = subprocess.Popen(
        [sys.executable, "-m", "mempalace", "mine", mempal_dir],
        stdout=log_f,
        stderr=log_f,
    )
    _write_auto_ingest_pid(proc.pid)
    return proc


def _maybe_auto_ingest():
    """If MEMPAL_DIR is set and exists, run mempalace mine in background."""
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        log_path = STATE_DIR / "hook.log"
        with open(log_path, "a", encoding="utf-8") as log_f:
            return _spawn_auto_ingest(log_f) is not None
    except OSError:
        return False


def _run_auto_ingest_sync(timeout: int = 60):
    """Run one best-effort foreground ingest without letting hook failures leak.

    Precompact hooks must always return a block decision. Slow or wedged mining
    should therefore degrade to "log and continue" instead of aborting the hook
    with TimeoutExpired or by launching a second overlapping miner.
    """
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        log_path = STATE_DIR / "hook.log"
        with open(log_path, "a", encoding="utf-8") as log_f:
            proc = _spawn_auto_ingest(log_f)
            if proc is None:
                return False

            try:
                proc.wait(timeout=timeout)
                return True
            except subprocess.TimeoutExpired:
                _log(f"Auto-ingest timed out after {timeout}s; terminating pid {proc.pid}")
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=5)
                return False
            finally:
                _clear_auto_ingest_pid(proc.pid)
    except OSError:
        return False


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
    """Precompact hook: always block with comprehensive save instruction."""
    parsed = _parse_harness_input(data, harness)
    session_id = parsed["session_id"]

    _log(f"PRE-COMPACT triggered for session {session_id}")

    # Optional: auto-ingest synchronously before compaction (so memories land first).
    # This remains best-effort: the hook itself must never fail open or crash.
    _run_auto_ingest_sync(timeout=60)

    # Always block -- compaction = save everything
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
