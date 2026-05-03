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

SAVE_INTERVAL = 10
STATE_DIR = Path.home() / ".mempalace" / "hook_state"


def _mempalace_python() -> str:
    """Return the python interpreter that has mempalace installed.

    When hooks are invoked by Claude Code, sys.executable may be the system
    python which lacks chromadb and other deps.  Resolution order:
    1. MEMPALACE_PYTHON env var (explicit override)
    2. Venv python from package install path
    3. Editable install: venv/ sibling to mempalace/
    4. sys.executable fallback
    """
    # Honor explicit override (used by shell hook wrappers)
    env_python = os.environ.get("MEMPALACE_PYTHON", "")
    if env_python and os.path.isfile(env_python) and os.access(env_python, os.X_OK):
        return env_python
    # This file lives at <venv>/lib/pythonX.Y/site-packages/mempalace/hooks_cli.py
    # or <project>/mempalace/hooks_cli.py (editable install).
    venv_bin = Path(__file__).resolve().parents[3] / "bin" / "python"
    if venv_bin.is_file():
        return str(venv_bin)
    # Editable install: assumes project root has a venv/ sibling to mempalace/
    project_venv = Path(__file__).resolve().parents[1] / "venv" / "bin" / "python"
    if project_venv.is_file():
        return str(project_venv)
    return sys.executable


_RECENT_MSG_COUNT = 30  # how many recent user messages to summarize

STOP_BLOCK_REASON = (
    "AUTO-SAVE checkpoint (MemPalace). Save this session's key content:\n"
    "1. mempalace_diary_write — session summary (what was discussed, "
    "key decisions, current state of work)\n"
    "2. mempalace_add_drawer — verbatim quotes, decisions, code snippets "
    "(place in appropriate wing and room)\n"
    "3. mempalace_kg_add — entity relationships (optional)\n"
    "For THIS save, use MemPalace MCP tools only (not auto-memory .md files). "
    "Use verbatim quotes where possible. Continue conversation after saving."
)

PRECOMPACT_BLOCK_REASON = (
    "COMPACTION IMMINENT (MemPalace). Save ALL session content before context is lost:\n"
    "1. mempalace_diary_write — thorough session summary\n"
    "2. mempalace_add_drawer — ALL verbatim quotes, decisions, code, context "
    "(place each in appropriate wing and room)\n"
    "3. mempalace_kg_add — entity relationships (optional)\n"
    "For THIS save, use MemPalace MCP tools only (not auto-memory .md files). "
    "Be thorough — after compaction this is all that survives. "
    "Save everything to MemPalace, then allow compaction to proceed."
)


def _sanitize_session_id(session_id: str) -> str:
    """Only allow alnum, dash, underscore to prevent path traversal."""
    sanitized = re.sub(r"[^a-zA-Z0-9_-]", "", session_id)
    return sanitized or "unknown"


def _validate_transcript_path(transcript_path: str) -> Path:
    """Validate and resolve a transcript path, rejecting paths outside expected roots.

    Returns a resolved Path if valid, or None if the path should be rejected.
    Accepted paths must:
    - Have a .jsonl or .json extension
    - Not contain '..' after resolution (path traversal prevention)
    """
    if not transcript_path:
        return None
    path = Path(transcript_path).expanduser().resolve()
    if path.suffix not in (".jsonl", ".json"):
        return None
    # Reject if the original input contained '..' traversal components
    if ".." in Path(transcript_path).parts:
        return None
    return path


def _normalize_text(text: str) -> str:
    """Normalize transcript text for lightweight heuristics."""
    return re.sub(r"\s+", " ", text).strip()


def _extract_text(content) -> str:
    """Flatten transcript content blocks into plain text."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        blocks = []
        for block in content:
            if isinstance(block, dict):
                text = block.get("text", "")
                if isinstance(text, str):
                    blocks.append(text)
        return " ".join(blocks)
    return ""


def _iter_real_messages(transcript_path: str):
    """Yield normalized user/assistant messages, excluding command chatter."""
    path = _validate_transcript_path(transcript_path)
    if path is None or not path.is_file():
        return
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                try:
                    entry = json.loads(line)
                    msg = entry.get("message", {})
                except (json.JSONDecodeError, AttributeError):
                    continue
                if not isinstance(msg, dict):
                    continue
                role = msg.get("role")
                if role not in {"user", "assistant"}:
                    continue
                text = _normalize_text(_extract_text(msg.get("content", "")))
                if not text or "<command-message>" in text:
                    continue
                yield role, text
    except OSError:
        return


def _iter_real_messages_any(transcript_path: str):
    """Yield user/assistant messages from ANY transcript format.
    
    Tries multiple schemas in order:
    1. Claude Code JSONL: {"message": {"role": ..., "content": ...}}
    2. Qwen JSONL: {"message": {"role": ..., "parts": [{"text": ...}]}}
    3. JSON files (Gemini, Claude sessions): via normalize.py
    4. normalize.py fallback for any format
    """
    path = _validate_transcript_path(transcript_path)
    if path is None or not path.is_file():
        return

    ext = path.suffix.lower()

    # Try Qwen JSONL schema: {"message": {"role": "...", "parts": [{"text": "..."}]}}
    if ext == ".jsonl":
        try:
            found = False
            with open(path, encoding="utf-8", errors="replace") as f:
                for line in f:
                    try:
                        entry = json.loads(line)
                    except (json.JSONDecodeError, AttributeError):
                        continue
                    msg = entry.get("message", {})
                    if not isinstance(msg, dict):
                        continue
                    role = msg.get("role")
                    if role not in {"user", "assistant"}:
                        continue
                    parts = msg.get("parts", [])
                    text = ""
                    if isinstance(parts, list):
                        text = " ".join(p.get("text", "") for p in parts if isinstance(p, dict))
                    if text and "<command-message>" not in text:
                        found = True
                        yield role, _normalize_text(text)
            if found:
                return
        except OSError:
            pass

    # Try standard JSONL schema (Claude Code, Codex)
    for role, text in _iter_real_messages(str(path)):
        yield role, text

    # For JSON files (Gemini, Claude session files), use normalize.py
    if ext == ".json":
        try:
            from mempalace.normalize import normalize
            transcript = normalize(str(path))
            if transcript and "> " in transcript:
                lines = transcript.split("\n")
                i = 0
                while i < len(lines):
                    if lines[i].startswith("> "):
                        yield "user", lines[i][2:].strip()
                        i += 1
                        if i < len(lines) and lines[i].strip() and not lines[i].startswith("> "):
                            yield "assistant", lines[i].strip()
                            i += 1
                    else:
                        i += 1
                return
        except Exception:
            pass

    # Final fallback: normalize.py for any format
    try:
        from mempalace.normalize import normalize
        transcript = normalize(str(path))
        if transcript and "> " in transcript:
            lines = transcript.split("\n")
            i = 0
            while i < len(lines):
                if lines[i].startswith("> "):
                    yield "user", lines[i][2:].strip()
                    i += 1
                    if i < len(lines) and lines[i].strip() and not lines[i].startswith("> "):
                        yield "assistant", lines[i].strip()
                        i += 1
                else:
                    i += 1
    except Exception:
        pass


def _count_human_messages(transcript_path: str) -> int:
    """Count human messages in any transcript format, skipping command chatter."""
    count = 0
    for role, _text in _iter_real_messages_any(transcript_path) or []:
        if role == "user":
            count += 1
    return count


_state_dir_initialized = False


def _log(message: str):
    """Append to hook state log file."""
    global _state_dir_initialized
    try:
        if not _state_dir_initialized:
            STATE_DIR.mkdir(parents=True, exist_ok=True)
            try:
                STATE_DIR.chmod(0o700)
            except (OSError, NotImplementedError):
                pass
            _state_dir_initialized = True
        log_path = STATE_DIR / "hook.log"
        is_new = not log_path.exists()
        timestamp = datetime.now().strftime("%H:%M:%S")
        with open(log_path, "a") as f:
            f.write(f"[{timestamp}] {message}\n")
        if is_new:
            try:
                log_path.chmod(0o600)
            except (OSError, NotImplementedError):
                pass
    except OSError:
        pass


def _output(data: dict):
    """Print JSON to stdout without importing modules that may redirect streams.

    If mempalace.mcp_server is already loaded, reuse its saved real stdout fd.
    Otherwise, write directly to fd 1 so hook responses still go to stdout even
    if sys.stdout has been redirected elsewhere.
    """
    payload = (json.dumps(data, indent=2, ensure_ascii=False) + "\n").encode("utf-8")

    real_stdout_fd: int | None = None
    mcp_mod = sys.modules.get("mempalace.mcp_server") or sys.modules.get(
        f"{__package__}.mcp_server" if __package__ else "mcp_server"
    )
    if mcp_mod is not None:
        real_stdout_fd = getattr(mcp_mod, "_REAL_STDOUT_FD", None)

    fd = real_stdout_fd if real_stdout_fd is not None else 1
    offset = 0
    try:
        while offset < len(payload):
            try:
                offset += os.write(fd, payload[offset:])
            except InterruptedError:
                continue
        return
    except OSError:
        pass

    sys.stdout.buffer.write(payload)
    sys.stdout.buffer.flush()


def _get_mine_targets() -> list[tuple[str, str]]:
    """Return the list of ``(dir, mode)`` targets for auto-ingest.

    MEMPAL_DIR (when set and resolvable) contributes a ``"projects"``
    target. Transcript ingestion is handled separately by
    ``_ingest_transcript`` — emitting it here too would double-mine the
    same JSONL into a different wing on every hook fire (#1231 review).

    An empty list means no MEMPAL_DIR ingest should run.
    """
    targets: list[tuple[str, str]] = []
    mempal_dir = os.environ.get("MEMPAL_DIR", "")
    if mempal_dir:
        resolved = Path(mempal_dir).expanduser().resolve()
        if resolved.is_dir():
            targets.append((str(resolved), "projects"))
    return targets


_MINE_PID_FILE = STATE_DIR / "mine.pid"


def _pid_alive(pid: int) -> bool:
    """Cross-platform existence check for a PID.

    On POSIX, ``os.kill(pid, 0)`` is the well-known no-op existence probe.
    On Windows, ``os.kill`` maps to ``TerminateProcess(handle, sig)`` and
    would *terminate* the target process with exit code ``sig`` — using
    it here would kill our own mine child (or worse, the caller itself).
    Use ``OpenProcess`` + ``GetExitCodeProcess`` via ctypes instead.
    """
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return False
        try:
            code = wintypes.DWORD()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return False
            return code.value == STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ValueError):
        return False


def _mine_already_running() -> bool:
    """Return True if a background mine process from a previous hook fire is still alive."""
    try:
        pid = int(_MINE_PID_FILE.read_text().strip())
    except (OSError, ValueError):
        return False
    return _pid_alive(pid)


def _spawn_mine(cmd: list) -> None:
    """Spawn a mine subprocess, write its PID to the lock file, log to hook.log."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    log_path = STATE_DIR / "hook.log"
    with open(log_path, "a") as log_f:
        proc = subprocess.Popen(cmd, stdout=log_f, stderr=log_f)
    _MINE_PID_FILE.write_text(str(proc.pid))


def _maybe_auto_ingest():
    """Background-mine MEMPAL_DIR (project files) if set.

    Transcript convos are ingested separately via ``_ingest_transcript``
    in the hook handlers — this function does not handle them, to avoid
    asymmetric interpreter handling and PID-file overwrite when both
    targets fire from a single hook call (#1231 review).
    """
    targets = _get_mine_targets()
    if not targets:
        return
    if _mine_already_running():
        _log("Skipping auto-ingest: mine already running")
        return
    for mine_dir, mode in targets:
        try:
            _spawn_mine([_mempalace_python(), "-m", "mempalace", "mine", mine_dir, "--mode", mode])
        except OSError:
            pass


def _mine_sync():
    """Synchronously mine MEMPAL_DIR (precompact path).

    Transcript convos are ingested separately via ``_ingest_transcript``
    in ``hook_precompact`` — keeping them out of this function avoids
    timeout stacking against the harness 30s ceiling (#1231 review).
    """
    targets = _get_mine_targets()
    if not targets:
        return
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    log_path = STATE_DIR / "hook.log"
    for mine_dir, mode in targets:
        try:
            with open(log_path, "a") as log_f:
                subprocess.run(
                    [
                        _mempalace_python(),
                        "-m",
                        "mempalace",
                        "mine",
                        mine_dir,
                        "--mode",
                        mode,
                    ],
                    stdout=log_f,
                    stderr=log_f,
                    timeout=60,
                )
        except (OSError, subprocess.TimeoutExpired):
            pass


def _desktop_toast(body: str, title: str = "MemPalace"):
    """Send a desktop notification via notify-send. Fails silently."""
    try:
        subprocess.Popen(
            ["notify-send", "--app-name=MemPalace", "--icon=brain", title, body],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        pass


def _extract_recent_messages(transcript_path: str, count: int = _RECENT_MSG_COUNT) -> list[str]:
    """Extract the last N user messages from any transcript format."""
    messages = []
    for role, text in _iter_real_messages_any(transcript_path) or []:
        if role == "user" and text.strip():
            messages.append(text.strip()[:200])
    return messages[-count:]


_THEME_STOPWORDS = frozenset(
    "the a an and or but in on at to for of is it i me my you your we our "
    "this that with from by was were be been are not no yes can do did dont "
    "will would should could have has had lets let just also like so if then "
    "ok okay sure yeah hey hi here there what when where how why which some "
    "all any each every about into out up down over after before between "
    "get got make made need want use used using check look see run try "
    "know think right now still already really very much more most too "
    "file files code one two new first last next thing things way well".split()
)


def _extract_themes(messages: list[str], max_themes: int = 3) -> list[str]:
    """Pull 2-3 distinctive topic words from recent messages.

    Note: stopword list is English-only; non-English corpora will produce noisy themes.
    """
    from collections import Counter

    words: Counter[str] = Counter()
    for msg in messages:
        for word in msg.lower().split():
            # Strip punctuation, keep words 4+ chars
            clean = word.strip(".,;:!?\"'`()[]{}#<>/\\-_=+@$%^&*~")
            if len(clean) >= 4 and clean not in _THEME_STOPWORDS and clean.isalpha():
                words[clean] += 1
    return [w for w, _ in words.most_common(max_themes)]


def _save_diary_direct(
    transcript_path: str,
    session_id: str,
    wing: str = "",
    toast: bool = False,
) -> dict:
    """Write a diary checkpoint by calling the tool function directly (no MCP roundtrip).

    If `wing` is set, the entry lands in that wing (typically the project wing
    derived from the transcript path). Otherwise falls back to `tool_diary_write`'s
    default of `wing_session-hook`.

    Returns {"count": N, "themes": [...]} on success, {"count": 0} on failure.
    """
    messages = _extract_recent_messages(transcript_path)
    if not messages:
        _log("No recent messages to save")
        return {"count": 0}

    themes = _extract_themes(messages)

    # Build a compressed diary entry from recent conversation
    now = datetime.now()
    topics = "|".join(m[:80] for m in messages[-10:])
    entry = (
        f"CHECKPOINT:{now.strftime('%Y-%m-%d')}|session:{session_id}"
        f"|msgs:{len(messages)}|recent:{topics}"
    )

    try:
        from .mcp_server import tool_diary_write

        result = tool_diary_write(
            agent_name="session-hook",
            entry=entry,
            topic="checkpoint",
            wing=wing,
        )
        if result.get("success"):
            _log(f"Diary checkpoint saved: {result.get('entry_id', '?')}")
            # Write state for ack tool to read
            try:
                ack_file = STATE_DIR / "last_checkpoint"
                ack_file.write_text(
                    json.dumps({"msgs": len(messages), "ts": now.isoformat()}),
                    encoding="utf-8",
                )
            except OSError:
                pass
            if toast:
                _desktop_toast(f"Checkpoint saved \u2014 {len(messages)} messages archived")
            return {"count": len(messages), "themes": themes}
        else:
            _log(f"Diary checkpoint failed: {result.get('error', 'unknown')}")
    except Exception as e:
        _log(f"Diary checkpoint error: {e}")
    return {"count": 0}


def _ingest_transcript(transcript_path: str):
    """Mine a Claude Code session transcript into the palace as a conversation."""
    path = _validate_transcript_path(transcript_path)
    if path is None or not path.is_file() or path.stat().st_size < 100:
        return

    from .config import MempalaceConfig

    try:
        MempalaceConfig()  # validate config loads
    except Exception:
        return

    try:
        log_path = STATE_DIR / "hook.log"
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        with open(log_path, "a") as log_f:
            subprocess.Popen(
                [
                    _mempalace_python(),
                    "-m",
                    "mempalace",
                    "mine",
                    str(path.parent),
                    "--mode",
                    "convos",
                    "--wing",
                    "sessions",
                ],
                stdout=log_f,
                stderr=log_f,
            )
        _log(f"Transcript ingest started: {path.name}")
    except OSError:
        pass


def _maybe_sync_obsidian():
    """Mirror recent memory changes into the Obsidian vault when available."""
    sync_script = Path.home() / "obsidian-vault" / "sync.py"
    if not sync_script.is_file():
        return
    try:
        log_path = STATE_DIR / "hook.log"
        with open(log_path, "a") as log_f:
            subprocess.Popen(
                [sys.executable, str(sync_script), "--quick"],
                stdout=log_f,
                stderr=log_f,
            )
    except OSError:
        pass


SUPPORTED_HARNESSES = {"claude-code", "claude", "codex", "opencode", "gemini", "qwen", "deepseek"}
SIGNAL_KEYWORDS = (
    "decision",
    "plan",
    "fix",
    "build",
    "implement",
    "found",
    "finding",
    "audit",
    "error",
    "blocker",
    "risk",
    "deploy",
    "architecture",
    "infra",
    "database",
    "metric",
    "source",
    "query",
    "report",
    "powerbi",
    "portal",
    "aws",
    "rds",
    "ecs",
    "mcp",
    "api",
    "route",
    "component",
    "dataset",
    "dax",
    "migration",
    "verify",
    "passed",
    "failed",
)
ARTIFACT_HINT_RE = re.compile(
    r"`[^`]+`|/[\w./-]+|\b[\w.-]+\.(?:ts|tsx|js|jsx|py|sh|md|sql|json|ya?ml|tf)\b|https?://",
    re.IGNORECASE,
)
TRIVIAL_MESSAGE_RE = re.compile(
    r"^(?:"
    r"continue|resume|go on|keep going|proceed|"
    r"ok(?:ay)?|k|yes|yep|no|nah|"
    r"thanks|thank you|good|sounds good|do it|go ahead|"
    r"continue please|switch and continue|"
    r"codex resume --last"
    r")(?:[.!? ]+)?$",
    re.IGNORECASE,
)


def _collect_unsaved_messages(transcript_path: str, last_save: int) -> list[str]:
    """Collect the message slice after the last checkpointed user message."""
    messages: list[str] = []
    user_count = 0
    for role, text in _iter_real_messages_any(transcript_path) or []:
        if role == "user":
            user_count += 1
            if user_count <= last_save:
                continue
        elif user_count <= last_save:
            continue
        messages.append(text)
    return messages


def _looks_trivial(text: str) -> bool:
    """Treat short acknowledgements as low signal."""
    normalized = _normalize_text(text).lower()
    if not normalized:
        return True
    if TRIVIAL_MESSAGE_RE.fullmatch(normalized):
        return True
    return len(normalized) < 8


def _has_meaningful_updates(messages: list[str]) -> bool:
    """Avoid blocking on chatter-only windows."""
    substantive: list[str] = []
    keyword_hits = 0
    artifact_hits = 0

    for text in messages:
        if _looks_trivial(text):
            continue
        lower = text.lower()
        has_keyword = any(keyword in lower for keyword in SIGNAL_KEYWORDS)
        artifact_count = len(list(ARTIFACT_HINT_RE.finditer(text)))
        if has_keyword:
            keyword_hits += 1
        artifact_hits += artifact_count
        if len(text) >= 30 or has_keyword or artifact_count:
            substantive.append(text)

    if not substantive:
        return False

    char_count = sum(len(text) for text in substantive)
    if keyword_hits >= 2:
        return True
    if artifact_hits >= 2:
        return True
    if len(substantive) >= 4 and char_count >= 300:
        return True
    if len(substantive) >= 2 and char_count >= 500:
        return True
    return False


def _parse_harness_input(data: dict, harness: str) -> dict:
    """Parse stdin JSON according to the harness type."""
    if harness not in SUPPORTED_HARNESSES:
        print(f"Unknown harness: {harness}", file=sys.stderr)
        sys.exit(1)
    return {
        "session_id": _sanitize_session_id(str(data.get("session_id", "unknown"))),
        "stop_hook_active": data.get("stop_hook_active", False),
        "transcript_path": str(data.get("transcript_path", "")),
        "cwd": str(data.get("cwd", "")),
        "source": str(data.get("source", "")),
    }


def _wing_from_transcript_path(transcript_path: str) -> str:
    """Derive a project wing name from a Claude Code transcript path.

    Claude Code encodes the project's source directory by replacing path
    separators with dashes, producing folders like:
        ~/.claude/projects/-home-<user>-Projects-<project>/session.jsonl
        ~/.claude/projects/-home-<user>-dev-<parent>-<project>/session.jsonl
        ~/.claude/projects/-Users-<user>-<folder>-<project>/session.jsonl

    The project directory name is the final dash-separated token of the
    encoded folder. Returns ``wing_<project>`` (lowercased, spaces → ``_``).
    Falls back to ``wing_sessions`` if the path does not match a Claude Code
    project-folder layout.
    """
    # Normalize path separators for cross-platform (Windows backslashes)
    normalized = transcript_path.replace("\\", "/")
    # Primary: pull the encoded project folder out of ``.claude/projects/``
    # and take its last dash-separated token.
    match = re.search(r"/\.claude/projects/-([^/]+)", normalized)
    if match:
        encoded = match.group(1)
        project = encoded.rsplit("-", 1)[-1]
        if project:
            return f"wing_{project.lower().replace(' ', '_')}"
    # Legacy fallback: explicit ``-Projects-<name>`` segment, useful for
    # transcripts not under the standard Claude Code projects dir.
    match = re.search(r"-Projects-([^/]+?)(?:/|$)", normalized)
    if match:
        project = match.group(1).lower().replace(" ", "_")
        return f"wing_{project}"
    return "wing_sessions"


def hook_stop(data: dict, harness: str):
    """Stop hook: block every N messages for auto-save."""
    parsed = _parse_harness_input(data, harness)
    session_id = parsed["session_id"]
    stop_hook_active = parsed["stop_hook_active"]
    transcript_path = parsed["transcript_path"]

    # If already in a block-mode save cycle, let through (infinite-loop prevention).
    # Silent mode saves directly without returning {"decision":"block"}, so there's
    # no loop to prevent — and Claude Code's plugin dispatch sets this flag on every
    # fire after the first, which would otherwise suppress all subsequent auto-saves.
    if str(stop_hook_active).lower() in ("true", "1", "yes"):
        # Safe default: assume silent mode on any config-read failure so saves
        # proceed rather than being silently dropped. Silent mode is the default
        # (v3.3.0+), so if we can't read config, behave as if it's still on.
        silent_guard = True
        try:
            from .config import MempalaceConfig
        except ImportError as exc:
            _log(
                f"WARNING: could not import MempalaceConfig for stop guard: {exc}; defaulting to silent mode"
            )
        else:
            try:
                silent_guard = MempalaceConfig().hook_silent_save
            except AttributeError as exc:
                _log(f"WARNING: could not read hook_silent_save: {exc}; defaulting to silent mode")
        if not silent_guard:
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
        unsaved_messages = _collect_unsaved_messages(transcript_path, last_save)
        if not _has_meaningful_updates(unsaved_messages):
            _log(f"SKIPPING SAVE at exchange {exchange_count}: low-signal window")
            _output({})
            return

        _log(f"TRIGGERING SAVE at exchange {exchange_count}")

        # Read hook settings from config
        from .config import MempalaceConfig
        
        # Optional: auto-ingest if MEMPAL_DIR is set
        _maybe_auto_ingest()
        _maybe_sync_obsidian()

        try:
            config = MempalaceConfig()
            silent = config.hook_silent_save
            toast = config.hook_desktop_toast
        except Exception:
            silent = True
            toast = False

        project_wing = _wing_from_transcript_path(transcript_path)

        if silent:
            # Save directly via Python API — systemMessage renders in terminal
            result = {"count": 0}
            if transcript_path:
                result = _save_diary_direct(
                    transcript_path, session_id, wing=project_wing, toast=toast
                )
                _ingest_transcript(transcript_path)
            # Only advance save marker after successful save
            count = result.get("count", 0)
            if count > 0:
                try:
                    last_save_file.write_text(str(exchange_count), encoding="utf-8")
                except OSError:
                    pass
                themes = result.get("themes", [])
                if themes:
                    tag = " \u2014 " + ", ".join(themes)
                else:
                    tag = ""
                
                # KG Integration: Include a fact summary in the silent feedback
                # to keep the agent's knowledge of entities fresh mid-session.
                try:
                    from .layers import MemoryStack
                    from .config import MempalaceConfig
                    stack = MemoryStack(palace_path=MempalaceConfig().palace_path)
                    kg_summary = stack.lkg.generate(limit=5)
                    kg_note = f"\n\n{kg_summary}" if "No current" not in kg_summary else ""
                except Exception:
                    kg_note = ""

                _output(
                    {
                        "systemMessage": f"\u2726 {count} memories woven into the palace{tag}{kg_note}",
                    }
                )
            else:
                _output({})
        else:
            # Legacy: block and ask Claude to save via MCP tools.
            # Marker advances before confirmed save — best-effort; if Claude
            # fails to save, the checkpoint is lost but won't retry endlessly.
            try:
                last_save_file.write_text(str(exchange_count), encoding="utf-8")
            except OSError:
                pass
            if transcript_path:
                _ingest_transcript(transcript_path)
            reason = STOP_BLOCK_REASON + f" Write diary entry to wing={project_wing}."
            _output({"decision": "block", "reason": reason})
    else:
        _output({})


def _wing_from_cwd(cwd: str) -> str:
    """Best-effort match of cwd to a known palace wing.

    Strategy: take cwd's basename and check it against the wings reported by
    `tool_status()`. Wings live in metadata, not on disk, so a directory check
    is unreliable.
    """
    if not cwd:
        return ""
    candidate = os.path.basename(cwd.rstrip("/"))
    if not candidate:
        return ""
    try:
        from .mcp_server import tool_status
        wings = tool_status().get("wings", {}) or {}
    except Exception:
        return ""
    return candidate if candidate in wings else ""


PROTOCOL_NUDGE = (
    "MemPalace protocol: BEFORE responding about projects/people/decisions, "
    "call mempalace_kg_query or mempalace_search to verify. WHEN making "
    "decisions/plans/architecture changes, call mempalace_add_drawer "
    "(room='decisions' or 'plans') and mempalace_kg_add for the relationships. "
    "AFTER each session, the Stop hook will prompt you to checkpoint — route "
    "those into the palace, not local files."
)


def _build_session_start_context(cwd: str, palace_path: str) -> str:
    """Build SessionStart additionalContext: wake-up text + protocol nudge.

    Wing match is based on the cwd's basename matching a palace wing directory.
    """
    sections: list[str] = []
    wing = _wing_from_cwd(cwd)
    try:
        from .layers import MemoryStack
        stack = MemoryStack(palace_path=palace_path)
        wake_text = stack.wake_up(wing=wing) if wing else stack.wake_up()
        if wake_text:
            header = (
                f"# MemPalace wake-up (wing={wing})"
                if wing else "# MemPalace wake-up"
            )
            sections.append(f"{header}\n\n{wake_text}")
    except Exception as exc:
        sections.append(f"# MemPalace wake-up unavailable: {exc}")
    sections.append(PROTOCOL_NUDGE)
    return "\n\n".join(sections)


def _wrap_session_start_output(harness: str, context: str) -> dict:
    """Format additionalContext per harness expectations.

    Claude Code uses hookSpecificOutput.additionalContext. Other harnesses
    that mimic Claude's schema accept the same shape; harnesses that don't
    will see a no-op (the unknown key is ignored).
    """
    if not context:
        return {}
    return {
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": context,
        }
    }


def hook_session_start(data: dict, harness: str):
    """Session start hook: inject palace context (status + wing match + protocol nudge)."""
    parsed = _parse_harness_input(data, harness)
    session_id = parsed["session_id"]
    cwd = parsed["cwd"]

    _log(f"SESSION START for session {session_id} cwd={cwd!r} harness={harness}")
    STATE_DIR.mkdir(parents=True, exist_ok=True)

    try:
        from .config import MempalaceConfig
        palace_path = MempalaceConfig().palace_path
    except Exception as exc:
        _log(f"SessionStart: cannot resolve palace_path ({exc}); skipping context inject")
        _output({})
        return

    context = _build_session_start_context(cwd, palace_path)
    _output(_wrap_session_start_output(harness, context))


def hook_precompact(data: dict, harness: str):
    """Precompact hook: mine transcript synchronously, then allow compaction."""
    parsed = _parse_harness_input(data, harness)
    session_id = parsed["session_id"]
    transcript_path = parsed["transcript_path"]

    _log(f"PRE-COMPACT triggered for session {session_id}")

    # Capture tool output via our normalize path before compaction loses it
    if transcript_path:
        _ingest_transcript(transcript_path)

    # Mine MEMPAL_DIR synchronously
    _mine_sync()

    # KG Integration: Check behavior mode for blocking
    # Supported: block (always), block_once (per session), proceed (never)
    mode = os.environ.get("MEMPAL_PRECOMPACT_MODE", "").lower()
    if not mode:
        # Default: proceed for Claude/Gemini (avoid hangs), block for others
        mode = "proceed" if harness in ("claude-code", "gemini") else "block"

    if mode == "proceed":
        _output({})
        return

    # Check session-once state if needed
    if mode == "block_once":
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        flag = STATE_DIR / f"{session_id}_precompact_blocked"
        if flag.exists():
            _output({})
            return
        flag.touch()

    # Block and force manual KG/Drawer save
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
