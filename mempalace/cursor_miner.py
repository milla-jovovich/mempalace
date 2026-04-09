#!/usr/bin/env python3
"""
cursor_miner.py — Mine Cursor AI chat sessions into the palace.

Reads store.db SQLite files from ~/.cursor/chats (or a custom directory),
extracts user ↔ assistant exchange pairs, and files them into the palace
with the same room-detection and dedup logic as convo_miner.

Each Cursor chat session is one workspace_hash/session_hash directory
containing a store.db SQLite database.  Blobs with role "user" or
"assistant" hold the actual conversation JSON.  User messages contain
the query inside a <user_query> tag (or plain text); assistant messages
have text in content[type=text] parts.
"""

import json
import os
import re
import shutil
import sqlite3
import hashlib
import tempfile
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from .convo_miner import detect_convo_room, get_collection, file_already_mined


MIN_CHUNK_SIZE = 30
ASSISTANT_TEXT_LIMIT = 1500  # chars per assistant turn to keep chunks focussed

_USER_QUERY_RE = re.compile(r"<user_query>(.*?)</user_query>", re.DOTALL)


# =============================================================================
# MESSAGE EXTRACTION
# =============================================================================


def _extract_user_text(content) -> str:
    """Extract the human-visible query from a Cursor user message."""
    raw = ""
    if isinstance(content, list):
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text":
                raw = part.get("text", "")
                break
    elif isinstance(content, str):
        raw = content

    m = _USER_QUERY_RE.search(raw)
    if m:
        return m.group(1).strip()

    # Skip pure system-context messages (no user_query tag and starts with XML)
    stripped = raw.strip()
    if stripped.startswith("<") and not m:
        return ""

    return stripped


def _extract_assistant_text(content) -> str:
    """Collect readable text parts from a Cursor assistant message."""
    parts = []
    if isinstance(content, list):
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text":
                txt = part.get("text", "").strip()
                if txt:
                    parts.append(txt)
    elif isinstance(content, str):
        return content.strip()
    return "\n".join(parts)


def _read_messages(db_path: str) -> tuple[list[dict], dict]:
    """Copy store.db to a temp file and return (messages, meta).

    Returns messages sorted by rowid (SQLite insertion order).
    meta is the decoded JSON from the meta table (session name, createdAt, etc.).
    """
    tmp_fd, tmp_path = tempfile.mkstemp(suffix=".db")
    os.close(tmp_fd)
    try:
        shutil.copy2(db_path, tmp_path)
        con = sqlite3.connect(tmp_path)
        cur = con.cursor()

        # Decode session metadata
        meta = {}
        try:
            cur.execute("SELECT value FROM meta WHERE key='0'")
            row = cur.fetchone()
            if row and row[0]:
                meta = json.loads(bytes.fromhex(row[0]))
        except Exception:
            pass

        # Extract ordered message blobs
        cur.execute("SELECT rowid, data FROM blobs ORDER BY rowid")
        messages = []
        for _rowid, data in cur.fetchall():
            if not data:
                continue
            try:
                parsed = json.loads(data)
                role = parsed.get("role")
                if role in ("user", "assistant"):
                    messages.append(
                        {
                            "role": role,
                            "content": parsed.get("content", []),
                        }
                    )
            except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
                pass  # binary blob

        con.close()
        return messages, meta
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


# =============================================================================
# CHUNKING
# =============================================================================


def chunk_cursor_session(messages: list[dict]) -> list[dict]:
    """Convert a list of role/content messages into exchange-pair chunks.

    Each chunk = one user question + the immediately following assistant reply.
    Assistant text is capped at ASSISTANT_TEXT_LIMIT chars to keep chunks
    focussed and retrieval-friendly.
    """
    chunks = []
    i = 0
    while i < len(messages):
        msg = messages[i]
        if msg["role"] != "user":
            i += 1
            continue

        user_text = _extract_user_text(msg["content"])
        if not user_text or len(user_text.strip()) < 5:
            i += 1
            continue

        # Scan forward for the next assistant message
        assistant_text = ""
        j = i + 1
        while j < len(messages):
            if messages[j]["role"] == "assistant":
                assistant_text = _extract_assistant_text(messages[j]["content"])
                break
            j += 1

        chunk_text = f"[User]\n{user_text}"
        if assistant_text:
            chunk_text += f"\n\n[Cursor]\n{assistant_text[:ASSISTANT_TEXT_LIMIT]}"

        if len(chunk_text.strip()) >= MIN_CHUNK_SIZE:
            chunks.append({"content": chunk_text, "chunk_index": len(chunks)})

        i = j + 1 if j < len(messages) and messages[j]["role"] == "assistant" else i + 1

    return chunks


# =============================================================================
# SCANNING
# =============================================================================


def scan_cursor_dbs(cursor_dir: str) -> list[tuple[str, str]]:
    """Walk cursor_dir and return (session_id, db_path) for every store.db.

    cursor_dir is expected to be ~/.cursor/chats (or equivalent).
    The session_id is "workspace_hash/session_hash" — unique per conversation.
    """
    results = []
    base = Path(cursor_dir).expanduser().resolve()
    if not base.is_dir():
        return results
    for workspace_dir in sorted(base.iterdir()):
        if not workspace_dir.is_dir():
            continue
        for session_dir in sorted(workspace_dir.iterdir()):
            if not session_dir.is_dir():
                continue
            db_path = session_dir / "store.db"
            if db_path.exists() and db_path.stat().st_size > 0:
                session_id = f"{workspace_dir.name}/{session_dir.name}"
                results.append((session_id, str(db_path)))
    return results


# =============================================================================
# MINE
# =============================================================================


def mine_cursor(
    cursor_dir: str,
    palace_path: str,
    wing: str = "cursor_chats",
    agent: str = "mempalace",
    limit: int = 0,
    dry_run: bool = False,
):
    """Mine Cursor AI chat sessions into the palace.

    Args:
        cursor_dir:  Path to ~/.cursor/chats (or equivalent).
        palace_path: Where the palace lives.
        wing:        Wing name (default: "cursor_chats").
        agent:       Provenance label stored on each drawer.
        limit:       Max sessions to process (0 = all).
        dry_run:     Show what would be filed without writing.
    """
    sessions = scan_cursor_dbs(cursor_dir)
    if limit > 0:
        sessions = sessions[:limit]

    print(f"\n{'=' * 55}")
    print("  MemPalace Mine — Cursor Chats")
    print(f"{'=' * 55}")
    print(f"  Wing:    {wing}")
    print(f"  Source:  {cursor_dir}")
    print(f"  Sessions found: {len(sessions)}")
    print(f"  Palace:  {palace_path}")
    if dry_run:
        print("  DRY RUN — nothing will be filed")
    print(f"{'-' * 55}\n")

    collection = get_collection(palace_path) if not dry_run else None

    total_drawers = 0
    sessions_skipped = 0
    room_counts: dict[str, int] = defaultdict(int)

    for i, (session_id, db_path) in enumerate(sessions, 1):
        source_key = f"cursor:{session_id}"

        if not dry_run and file_already_mined(collection, source_key):
            sessions_skipped += 1
            continue

        try:
            messages, meta = _read_messages(db_path)
        except Exception:
            continue

        if not messages:
            continue

        chunks = chunk_cursor_session(messages)
        if not chunks:
            continue

        # Session context for metadata
        session_name = meta.get("name", session_id.split("/")[-1][:40])
        created_ts = meta.get("createdAt")
        created_iso = (
            datetime.fromtimestamp(created_ts / 1000).isoformat()
            if isinstance(created_ts, (int, float))
            else None
        )

        # Room from full session text (use first ~3000 chars)
        preview = " ".join(c["content"] for c in chunks[:4])
        room = detect_convo_room(preview)

        if dry_run:
            print(
                f"  [DRY RUN] {session_name[:40]:40} -> room:{room} ({len(chunks)} drawers)"
            )
            total_drawers += len(chunks)
            room_counts[room] += 1
            continue

        room_counts[room] += 1
        drawers_added = 0
        for chunk in chunks:
            drawer_id = (
                "drawer_"
                + wing
                + "_"
                + room
                + "_"
                + hashlib.md5(
                    (source_key + str(chunk["chunk_index"])).encode(),
                    usedforsecurity=False,
                ).hexdigest()[:16]
            )
            metadata: dict = {
                "wing": wing,
                "room": room,
                "source_file": source_key,
                "chunk_index": chunk["chunk_index"],
                "added_by": agent,
                "filed_at": datetime.now().isoformat(),
                "ingest_mode": "cursor_chats",
                "session_name": session_name,
                "workspace_hash": session_id.split("/")[0],
            }
            if created_iso:
                metadata["session_created_at"] = created_iso

            try:
                collection.add(
                    documents=[chunk["content"]],
                    ids=[drawer_id],
                    metadatas=[metadata],
                )
                drawers_added += 1
            except Exception as e:
                if "already exists" not in str(e).lower():
                    raise

        total_drawers += drawers_added
        label = session_name[:45]
        print(f"  + [{i:3}/{len(sessions)}] {label:45} +{drawers_added}")

    print(f"\n{'=' * 55}")
    print("  Done.")
    print(f"  Sessions processed: {len(sessions) - sessions_skipped}")
    print(f"  Sessions skipped (already filed): {sessions_skipped}")
    print(f"  Drawers filed: {total_drawers}")
    if room_counts:
        print("\n  By room:")
        for room, count in sorted(room_counts.items(), key=lambda x: -x[1]):
            print(f"    {room:20} {count}")
    print('\n  Next: mempalace search "what you\'re looking for"')
    print(f"{'=' * 55}\n")
