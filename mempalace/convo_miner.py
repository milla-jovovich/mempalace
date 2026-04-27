#!/usr/bin/env python3
"""
convo_miner.py — Mine conversations into the palace.

Ingests chat exports (Claude Code, ChatGPT, Slack, plain text transcripts).
Normalizes format, chunks by exchange pair (Q+A = one unit), files to palace.

Same palace as project mining. Different ingest strategy.
"""

import os
import sys
import hashlib
from pathlib import Path
from datetime import datetime
from collections import defaultdict
from typing import Optional

from .normalize import normalize
from .palace import (
    NORMALIZE_VERSION,
    SKIP_DIRS,
    file_already_mined,
    get_collection,
    mine_lock,
)


# Cached hall keywords — avoids re-reading config per drawer
_HALL_KEYWORDS_CACHE = None


def _detect_hall_cached(content: str) -> str:
    """Route content to a hall using cached keywords. Same logic as miner.detect_hall."""
    global _HALL_KEYWORDS_CACHE
    if _HALL_KEYWORDS_CACHE is None:
        from .config import MempalaceConfig

        _HALL_KEYWORDS_CACHE = MempalaceConfig().hall_keywords
    content_lower = content[:3000].lower()
    scores = {}
    for hall, keywords in _HALL_KEYWORDS_CACHE.items():
        score = sum(1 for kw in keywords if kw in content_lower)
        if score > 0:
            scores[hall] = score
    return max(scores, key=scores.get) if scores else "general"


# File types that might contain conversations
CONVO_EXTENSIONS = {
    ".txt",
    ".md",
    ".json",
    ".jsonl",
}

MIN_CHUNK_SIZE = 30
CHUNK_SIZE = 800  # chars per drawer — align with miner.py
DRAWER_UPSERT_BATCH_SIZE = 1000
MAX_FILE_SIZE = 500 * 1024 * 1024  # 500 MB — skip files larger than this.
# Matches miner.py at 500 MB. Long Claude Code sessions, multi-year
# ChatGPT exports, and lifetime Slack dumps routinely exceed 10 MB; the
# cap at that level silently dropped them with `continue`. Per-drawer
# size is bounded by CHUNK_SIZE, but larger source files still produce
# more drawers and therefore more embedding/storage work — and content
# is normalized and loaded fully into memory before chunking, so memory
# use also scales with source size.


def _register_file(collection, source_file: str, wing: str, agent: str):
    """Write a sentinel so file_already_mined() returns True for 0-chunk files.

    Without this, files that normalize to nothing or produce zero chunks are
    re-read and re-processed on every mine run because nothing was written to
    ChromaDB on the first pass.
    """
    sentinel_id = f"_reg_{hashlib.sha256(source_file.encode()).hexdigest()[:24]}"
    collection.upsert(
        documents=[f"[registry] {source_file}"],
        ids=[sentinel_id],
        metadatas=[
            {
                "wing": wing,
                "room": "_registry",
                "source_file": source_file,
                "added_by": agent,
                "filed_at": datetime.now().isoformat(),
                "ingest_mode": "registry",
                "normalize_version": NORMALIZE_VERSION,
            }
        ],
    )


# =============================================================================
# CHUNKING — exchange pairs for conversations
# =============================================================================


def chunk_exchanges(content: str) -> list:
    """
    Chunk by exchange pair: one > turn + AI response = one unit.
    Falls back to paragraph chunking if no > markers.
    """
    lines = content.split("\n")
    quote_lines = sum(1 for line in lines if line.strip().startswith(">"))

    if quote_lines >= 3:
        return _chunk_by_exchange(lines)
    else:
        return _chunk_by_paragraph(content)


def _chunk_by_exchange(lines: list) -> list:
    """One user turn (>) + the AI response that follows = one or more chunks.

    The full AI response is preserved verbatim.  When the combined
    user-turn + response exceeds CHUNK_SIZE the response is split across
    consecutive drawers so nothing is silently discarded.
    """
    chunks = []
    i = 0

    while i < len(lines):
        line = lines[i]
        if line.strip().startswith(">"):
            user_turn = line.strip()
            i += 1

            ai_lines = []
            while i < len(lines):
                next_line = lines[i]
                if next_line.strip().startswith(">") or next_line.strip().startswith("---"):
                    break
                if next_line.strip():
                    ai_lines.append(next_line.strip())
                i += 1

            ai_response = " ".join(ai_lines)
            content = f"{user_turn}\n{ai_response}" if ai_response else user_turn

            # Split into multiple drawers when the exchange exceeds CHUNK_SIZE
            if len(content) > CHUNK_SIZE:
                # First chunk: user turn + as much response as fits
                first_part = content[:CHUNK_SIZE]
                if len(first_part.strip()) > MIN_CHUNK_SIZE:
                    chunks.append({"content": first_part, "chunk_index": len(chunks)})
                # Remaining response in CHUNK_SIZE-sized continuation drawers
                remainder = content[CHUNK_SIZE:]
                while remainder:
                    part = remainder[:CHUNK_SIZE]
                    remainder = remainder[CHUNK_SIZE:]
                    if len(part.strip()) > MIN_CHUNK_SIZE:
                        chunks.append({"content": part, "chunk_index": len(chunks)})
            elif len(content.strip()) > MIN_CHUNK_SIZE:
                chunks.append(
                    {
                        "content": content,
                        "chunk_index": len(chunks),
                    }
                )
        else:
            i += 1

    return chunks


def _chunk_by_paragraph(content: str) -> list:
    """Fallback: chunk by paragraph breaks."""
    chunks = []
    paragraphs = [p.strip() for p in content.split("\n\n") if p.strip()]

    # If no paragraph breaks and long content, chunk by line groups
    if len(paragraphs) <= 1 and content.count("\n") > 20:
        lines = content.split("\n")
        for i in range(0, len(lines), 25):
            group = "\n".join(lines[i : i + 25]).strip()
            if len(group) > MIN_CHUNK_SIZE:
                chunks.append({"content": group, "chunk_index": len(chunks)})
        return chunks

    for para in paragraphs:
        if len(para) > MIN_CHUNK_SIZE:
            chunks.append({"content": para, "chunk_index": len(chunks)})

    return chunks


# =============================================================================
# ROOM DETECTION — topic-based for conversations
# =============================================================================

TOPIC_KEYWORDS = {
    "technical": [
        "code",
        "python",
        "function",
        "bug",
        "error",
        "api",
        "database",
        "server",
        "deploy",
        "git",
        "test",
        "debug",
        "refactor",
    ],
    "architecture": [
        "architecture",
        "design",
        "pattern",
        "structure",
        "schema",
        "interface",
        "module",
        "component",
        "service",
        "layer",
    ],
    "planning": [
        "plan",
        "roadmap",
        "milestone",
        "deadline",
        "priority",
        "sprint",
        "backlog",
        "scope",
        "requirement",
        "spec",
    ],
    "decisions": [
        "decided",
        "chose",
        "picked",
        "switched",
        "migrated",
        "replaced",
        "trade-off",
        "alternative",
        "option",
        "approach",
    ],
    "problems": [
        "problem",
        "issue",
        "broken",
        "failed",
        "crash",
        "stuck",
        "workaround",
        "fix",
        "solved",
        "resolved",
    ],
}


def detect_convo_room(content: str) -> str:
    """Score conversation content against topic keywords."""
    content_lower = content[:3000].lower()
    scores = {}
    for room, keywords in TOPIC_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw in content_lower)
        if score > 0:
            scores[room] = score
    if scores:
        return max(scores, key=scores.get)
    return "general"


# =============================================================================
# PALACE OPERATIONS
# =============================================================================


# =============================================================================
# SCAN FOR CONVERSATION FILES
# =============================================================================


def scan_convos(convo_dir: str) -> list:
    """Find all potential conversation files."""
    convo_path = Path(convo_dir).expanduser().resolve()
    files = []
    for root, dirs, filenames in os.walk(convo_path):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for filename in filenames:
            if filename.endswith(".meta.json"):
                continue
            filepath = Path(root) / filename
            if filepath.suffix.lower() in CONVO_EXTENSIONS:
                # Skip symlinks and oversized files
                if filepath.is_symlink():
                    continue
                try:
                    if filepath.stat().st_size > MAX_FILE_SIZE:
                        continue
                except OSError:
                    continue
                files.append(filepath)
    return files


# =============================================================================
# MINE CONVERSATIONS
# =============================================================================


def _file_chunks_locked(collection, source_file, chunks, wing, room, agent, extract_mode):
    """Lock the source file, purge stale drawers, and upsert fresh chunks.

    Combines the per-file serialization that prevents concurrent agents from
    duplicating work (via mine_lock) with the normalize-version rebuild
    contract (purge-before-insert so pre-v2 drawers don't survive).

    Returns (drawers_added, room_counts_delta, skipped).
    """
    room_counts_delta: dict = defaultdict(int)
    drawers_added = 0
    with mine_lock(source_file):
        # Re-check after lock — another agent may have just finished this file
        # at the current schema. A stale-version hit here returns False, so we
        # still fall through to the purge+rebuild path below.
        if file_already_mined(collection, source_file):
            return 0, room_counts_delta, True

        # Purge stale drawers first. When the normalize schema bumps,
        # file_already_mined() returned False for pre-v2 drawers — clean
        # them out so the source doesn't end up with mixed old/new drawers.
        try:
            collection.delete(where={"source_file": source_file})
        except Exception:
            pass

        # Batch chunks into bounded upserts so large transcripts keep most of
        # the embedding speedup without one huge Chroma/SQLite request. Keep
        # one filed_at per source file so all transcript drawers share an
        # ingest timestamp.
        filed_at = datetime.now().isoformat()
        for batch_start in range(0, len(chunks), DRAWER_UPSERT_BATCH_SIZE):
            batch_docs: list = []
            batch_ids: list = []
            batch_metas: list = []
            for chunk in chunks[batch_start : batch_start + DRAWER_UPSERT_BATCH_SIZE]:
                chunk_room = chunk.get("memory_type", room) if extract_mode == "general" else room
                if extract_mode == "general":
                    room_counts_delta[chunk_room] += 1
                drawer_id = f"drawer_{wing}_{chunk_room}_{hashlib.sha256((source_file + str(chunk['chunk_index'])).encode()).hexdigest()[:24]}"
                batch_docs.append(chunk["content"])
                batch_ids.append(drawer_id)
                batch_metas.append(
                    {
                        "wing": wing,
                        "room": chunk_room,
                        "hall": _detect_hall_cached(chunk["content"]),
                        "source_file": source_file,
                        "chunk_index": chunk["chunk_index"],
                        "added_by": agent,
                        "filed_at": filed_at,
                        "ingest_mode": "convos",
                        "extract_mode": extract_mode,
                        "normalize_version": NORMALIZE_VERSION,
                    }
                )
            try:
                collection.upsert(
                    documents=batch_docs,
                    ids=batch_ids,
                    metadatas=batch_metas,
                )
                drawers_added += len(batch_docs)
            except Exception as e:
                if "already exists" not in str(e).lower():
                    raise
    return drawers_added, room_counts_delta, False


def _is_ai_tool_path(path: Path) -> bool:
    """Return True when `path` lives inside a known AI-tool storage dir.

    Detected paths (exact-segment match — substrings like `.gemini-backup`
    or `.codex-archive` do NOT match):
      - any segment ``.codex`` (Codex CLI sessions / archives)
      - any segment ``.gemini`` (Gemini CLI sessions under ~/.gemini/tmp/...)
      - the consecutive segment pair ``.claude/projects`` (Claude Code).
        ``.claude`` alone is NOT matched — that is the settings/config dir,
        not a conversation source.

    Used by ``_resolve_wing`` to default the destination wing to
    ``wing_api`` when the user hasn't passed an explicit ``--wing``.
    """
    try:
        parts = path.resolve().parts
    except (OSError, RuntimeError):
        return False

    if ".codex" in parts:
        return True
    if ".gemini" in parts:
        return True
    for i in range(len(parts) - 1):
        if parts[i] == ".claude" and parts[i + 1] == "projects":
            return True
    return False


def _resolve_wing(convo_path: Path, wing: Optional[str]) -> str:
    """Determine the destination wing for ``mine_convos``.

    Precedence (first match wins):

      1. Explicit ``wing`` argument from the user — always wins, even on
         an AI-tool path. Empty string is treated as "no wing".
      2. AI-tool path detection — defaults to ``wing_api`` so Claude
         Code / Codex / Gemini conversations group under a single wing
         dedicated to API-sourced content.
      3. Basename fallback — sanitized via ``config.normalize_wing_name``
         (lowercase, spaces/hyphens collapsed to underscores). Shared
         single source of truth with ``cmd_init``,
         ``room_detector_local``, and ``miner.load_config`` so all
         wing-slug producers stay in sync (per #1194 consolidation).
    """
    from .config import normalize_wing_name

    if wing:
        return wing
    if _is_ai_tool_path(convo_path):
        return "wing_api"
    return normalize_wing_name(convo_path.name)


def mine_convos(
    convo_dir: str,
    palace_path: str,
    wing: str = None,
    agent: str = "mempalace",
    limit: int = 0,
    dry_run: bool = False,
    extract_mode: str = "exchange",
):
    """Mine a directory of conversation files into the palace.

    extract_mode:
        "exchange" — default exchange-pair chunking (Q+A = one unit)
        "general"  — general extractor: decisions, preferences, milestones, problems, emotions
    """

    convo_path = Path(convo_dir).expanduser().resolve()
    wing = _resolve_wing(convo_path, wing)

    files = scan_convos(convo_dir)
    if limit > 0:
        files = files[:limit]

    print(f"\n{'=' * 55}")
    print("  MemPalace Mine — Conversations")
    print(f"{'=' * 55}")
    print(f"  Wing:    {wing}")
    print(f"  Source:  {convo_path}")
    print(f"  Files:   {len(files)}")
    print(f"  Palace:  {palace_path}")
    if dry_run:
        print("  DRY RUN — nothing will be filed")
    print(f"{'-' * 55}\n")

    collection = get_collection(palace_path) if not dry_run else None

    total_drawers = 0
    files_skipped = 0
    room_counts = defaultdict(int)

    for i, filepath in enumerate(files, 1):
        source_file = str(filepath)

        # Skip if already filed
        if not dry_run and file_already_mined(collection, source_file):
            files_skipped += 1
            continue

        # Normalize format
        try:
            content = normalize(str(filepath))
        except (OSError, ValueError):
            if not dry_run:
                _register_file(collection, source_file, wing, agent)
            continue

        if not content or len(content.strip()) < MIN_CHUNK_SIZE:
            if not dry_run:
                _register_file(collection, source_file, wing, agent)
            continue

        # Chunk — either exchange pairs or general extraction
        if extract_mode == "general":
            from .general_extractor import extract_memories

            chunks = extract_memories(content)
            # Each chunk already has memory_type; use it as the room name
        else:
            chunks = chunk_exchanges(content)

        if not chunks:
            if not dry_run:
                _register_file(collection, source_file, wing, agent)
            continue

        # Detect room from content (general mode uses memory_type instead)
        if extract_mode != "general":
            room = detect_convo_room(content)
        else:
            room = None  # set per-chunk below

        if dry_run:
            if extract_mode == "general":
                from collections import Counter

                type_counts = Counter(c.get("memory_type", "general") for c in chunks)
                types_str = ", ".join(f"{t}:{n}" for t, n in type_counts.most_common())
                print(f"    [DRY RUN] {filepath.name} → {len(chunks)} memories ({types_str})")
            else:
                print(f"    [DRY RUN] {filepath.name} → room:{room} ({len(chunks)} drawers)")
            total_drawers += len(chunks)
            # Track room counts
            if extract_mode == "general":
                for c in chunks:
                    room_counts[c.get("memory_type", "general")] += 1
            else:
                room_counts[room] += 1
            continue

        if extract_mode != "general":
            room_counts[room] += 1

        # Lock + purge stale + file fresh chunks. Lock serializes concurrent
        # agents; purge removes pre-v2 drawers so the schema bump applies.
        drawers_added, room_delta, skipped = _file_chunks_locked(
            collection, source_file, chunks, wing, room, agent, extract_mode
        )
        if skipped:
            files_skipped += 1
            continue
        for r, n in room_delta.items():
            room_counts[r] += n

        total_drawers += drawers_added
        print(f"  + [{i:4}/{len(files)}] {filepath.name[:50]:50} +{drawers_added}")

    print(f"\n{'=' * 55}")
    print("  Done.")
    print(f"  Files processed: {len(files) - files_skipped}")
    print(f"  Files skipped (already filed): {files_skipped}")
    print(f"  Drawers filed: {total_drawers}")
    if room_counts:
        print("\n  By room:")
        for room, count in sorted(room_counts.items(), key=lambda x: x[1], reverse=True):
            print(f"    {room:20} {count} files")
    print('\n  Next: mempalace search "what you\'re looking for"')
    print(f"{'=' * 55}\n")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python convo_miner.py <convo_dir> [--palace PATH] [--limit N] [--dry-run]")
        sys.exit(1)
    from .config import MempalaceConfig

    mine_convos(sys.argv[1], palace_path=MempalaceConfig().palace_path)
