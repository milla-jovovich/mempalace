#!/usr/bin/env python3
"""mempal_precompact.py — Emergency save before context compaction.

PreCompact hook. Always blocks, telling the AI to save everything
before the context window gets compressed and detailed context is lost.
"""

import json
import re
import sys
from datetime import datetime
from pathlib import Path

STATE_DIR = Path.home() / ".mempalace" / "hook_state"


def main():
    try:
        hook_input = json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError):
        hook_input = {}

    session_id = hook_input.get("session_id", "unknown")

    # Log
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    log_file = STATE_DIR / "hook.log"
    safe_id = re.sub(r"[^a-zA-Z0-9_-]", "_", session_id) or "unknown"
    safe_id = safe_id[:200]
    try:
        with open(log_file, "a") as f:
            ts = datetime.now().strftime("%H:%M:%S")
            f.write(f"[{ts}] PRE-COMPACT triggered for session {safe_id}\n")
    except OSError:
        pass

    # Always block — compaction always warrants a save
    print(
        json.dumps(
            {
                "decision": "block",
                "reason": "COMPACTION IMMINENT. Save ALL topics, decisions, quotes, code, and important context from this session to your memory system. Be thorough — after compaction, detailed context will be lost. Organize into appropriate categories. Use verbatim quotes where possible. Save everything, then allow compaction to proceed.",
            }
        )
    )
    sys.stdout.flush()


if __name__ == "__main__":
    main()
