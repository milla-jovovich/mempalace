#!/usr/bin/env python3
"""mempal_save.py — Auto-save checkpoint every N human messages.

Stop hook. Counts human messages in the session transcript and blocks
every SAVE_INTERVAL messages, telling the AI to save key memories to
the palace. Uses stop_hook_active flag to prevent infinite loops.
"""

import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

SAVE_INTERVAL = 15
STATE_DIR = Path.home() / ".mempalace" / "hook_state"


def main():
    try:
        hook_input = json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError):
        return

    session_id = hook_input.get("session_id", "unknown")
    stop_hook_active = hook_input.get("stop_hook_active", False)
    transcript_path = hook_input.get("transcript_path", "")

    # If already in a save cycle, let the AI stop normally
    if stop_hook_active:
        return

    # Expand ~ and validate path
    if transcript_path:
        transcript_path = os.path.expanduser(transcript_path)

    # Count human messages in the JSONL transcript
    exchange_count = 0
    if transcript_path and os.path.isfile(transcript_path):
        try:
            with open(transcript_path) as f:
                for line in f:
                    try:
                        entry = json.loads(line)
                        msg = entry.get("message", {})
                        if isinstance(msg, dict) and msg.get("role") == "user":
                            content = msg.get("content", "")
                            if isinstance(content, str) and "<command-message>" in content:
                                continue
                            exchange_count += 1
                    except (json.JSONDecodeError, AttributeError):
                        pass
        except OSError:
            pass

    # Track last save point — sanitize session_id for filename safety
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    safe_id = re.sub(r"[^a-zA-Z0-9_-]", "_", session_id) or "unknown"
    safe_id = safe_id[:200]  # Avoid ENAMETOOLONG on ext4/APFS
    last_save_file = STATE_DIR / f"{safe_id}_last_save"

    last_save = 0
    if last_save_file.is_file():
        try:
            last_save = int(last_save_file.read_text().strip())
        except (ValueError, OSError):
            pass

    since_last = exchange_count - last_save

    # Log for debugging
    log_file = STATE_DIR / "hook.log"
    try:
        with open(log_file, "a") as f:
            ts = datetime.now().strftime("%H:%M:%S")
            f.write(
                f"[{ts}] Session {safe_id}: {exchange_count} exchanges, {since_last} since last save\n"
            )
    except OSError:
        pass

    # Time to save?
    if since_last >= SAVE_INTERVAL and exchange_count > 0:
        last_save_file.write_text(str(exchange_count))

        try:
            with open(log_file, "a") as f:
                ts = datetime.now().strftime("%H:%M:%S")
                f.write(f"[{ts}] TRIGGERING SAVE at exchange {exchange_count}\n")
        except OSError:
            pass

        print(
            json.dumps(
                {
                    "decision": "block",
                    "reason": "AUTO-SAVE checkpoint. Save key topics, decisions, quotes, and code from this session to your memory system. Organize into appropriate categories. Use verbatim quotes where possible. Continue conversation after saving.",
                }
            )
        )
        sys.stdout.flush()


if __name__ == "__main__":
    main()
