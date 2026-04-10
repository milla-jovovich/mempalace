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
from concurrent.futures import ThreadPoolExecutor, as_completed

from .normalize import normalize
from .palace import SKIP_DIRS, get_collection, file_already_mined


# File types that might contain conversations
CONVO_EXTENSIONS = {
    ".txt",
    ".md",
    ".json",
    ".jsonl",
}

MIN_CHUNK_SIZE = 30
BATCH_SIZE = 128  # chunks per upsert call (matches miner.py)
MAX_WORKERS = min(32, (os.cpu_count() or 4) * 2)
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB — skip files larger than this


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
    """One user turn (>) + the AI response that follows = one chunk."""
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

            ai_response = " ".join(ai_lines[:8])
            content = f"{user_turn}\n{ai_response}" if ai_response else user_turn

            if len(content.strip()) > MIN_CHUNK_SIZE:
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


def process_convo_file_cpu(
    filepath: Path,
    wing: str,
    agent: str,
    extract_mode: str,
) -> "tuple | None":
    """
    Pure CPU worker: normalize, chunk, detect room, build drawer records.
    Thread-safe — no ChromaDB calls, no shared state.

    Returns (source_file, room, records, room_counts_delta) or None if skipped.
    """
    source_file = str(filepath)

    try:
        content = normalize(source_file)
    except (OSError, ValueError):
        return None

    if not content or len(content.strip()) < MIN_CHUNK_SIZE:
        return None

    if extract_mode == "general":
        from .general_extractor import extract_memories

        chunks = extract_memories(content)
    else:
        chunks = chunk_exchanges(content)

    if not chunks:
        return None

    if extract_mode != "general":
        room = detect_convo_room(content)
    else:
        room = None

    now = datetime.now().isoformat()
    records = []
    room_counts_delta = defaultdict(int)

    if extract_mode != "general":
        room_counts_delta[room] = 1

    for chunk in chunks:
        chunk_room = chunk.get("memory_type", room) if extract_mode == "general" else room
        if extract_mode == "general":
            room_counts_delta[chunk_room] += 1

        drawer_id = (
            f"drawer_{wing}_{chunk_room}_"
            + hashlib.sha256(
                (source_file + str(chunk["chunk_index"])).encode()
            ).hexdigest()[:24]
        )
        meta = {
            "wing": wing,
            "room": chunk_room,
            "source_file": source_file,
            "chunk_index": chunk["chunk_index"],
            "added_by": agent,
            "filed_at": now,
            "ingest_mode": "convos",
            "extract_mode": extract_mode,
        }
        records.append((drawer_id, chunk["content"], meta))

    return source_file, room, records, dict(room_counts_delta)


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
    if not wing:
        wing = convo_path.name.lower().replace(" ", "_").replace("-", "_")

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

    # ------------------------------------------------------------------
    # DRY RUN: sequential, no writes
    # ------------------------------------------------------------------
    if dry_run:
        for i, filepath in enumerate(files, 1):
            result = process_convo_file_cpu(filepath, wing, agent, extract_mode)
            if result is None:
                continue
            _, room, records, room_counts_delta = result
            if extract_mode == "general":
                from collections import Counter

                type_counts = Counter(meta["room"] for (_, _, meta) in records)
                types_str = ", ".join(f"{t}:{n}" for t, n in type_counts.most_common())
                print(f"    [DRY RUN] {filepath.name} → {len(records)} memories ({types_str})")
            else:
                print(f"    [DRY RUN] {filepath.name} → room:{room} ({len(records)} drawers)")
            total_drawers += len(records)
            for r, c in room_counts_delta.items():
                room_counts[r] += c

    # ------------------------------------------------------------------
    # REAL MINE: parallel file processing + batched upserts
    # ------------------------------------------------------------------
    else:
        print(f"  Checking {len(files)} files for changes...")
        pending = [fp for fp in files if not file_already_mined(collection, str(fp))]
        already_mined = len(files) - len(pending)

        batch_ids, batch_docs, batch_metas = [], [], []
        completed = 0
        skipped_small = 0

        def flush_batch(ids, docs, metas):
            if ids:
                collection.upsert(documents=docs, ids=ids, metadatas=metas)
                ids.clear()
                docs.clear()
                metas.clear()

        try:
            with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
                futures = {
                    executor.submit(
                        process_convo_file_cpu, fp, wing, agent, extract_mode
                    ): fp
                    for fp in pending
                }
                for future in as_completed(futures):
                    filepath = futures[future]
                    try:
                        result = future.result()
                    except Exception as e:
                        print(f"  ! [ERROR] {filepath.name}: {e}")
                        completed += 1
                        continue
                    completed += 1
                    if result is None:
                        skipped_small += 1
                        continue
                    source_file, room, records, room_counts_delta = result
                    for drawer_id, chunk_content, meta in records:
                        batch_ids.append(drawer_id)
                        batch_docs.append(chunk_content)
                        batch_metas.append(meta)
                        if len(batch_ids) >= BATCH_SIZE:
                            flush_batch(batch_ids, batch_docs, batch_metas)
                    total_drawers += len(records)
                    for r, c in room_counts_delta.items():
                        room_counts[r] += c
                    print(
                        f"  ✓ [{completed:4}/{len(pending)}] "
                        f"{Path(source_file).name[:50]:50} +{len(records)}"
                    )
        finally:
            flush_batch(batch_ids, batch_docs, batch_metas)

        files_skipped = already_mined + skipped_small

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
