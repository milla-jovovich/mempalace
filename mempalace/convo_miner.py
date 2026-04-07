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
from dataclasses import dataclass, field
from pathlib import Path
from datetime import datetime
from collections import defaultdict

from .drawer_store import DrawerNamespace, DrawerStore, REFRESH_OWNER_KEY
from .normalize import join_normalized_segments, normalize_segments


# File types that might contain conversations
CONVO_EXTENSIONS = {
    ".txt",
    ".md",
    ".json",
    ".jsonl",
}

SKIP_DIRS = {
    ".git",
    "node_modules",
    "__pycache__",
    ".venv",
    "venv",
    "env",
    "dist",
    "build",
    ".next",
    ".mempalace",
}

MIN_CHUNK_SIZE = 30
CONVO_PIPELINE_FINGERPRINTS = {
    "exchange": f"convos:exchange:v2:min={MIN_CHUNK_SIZE}:chunking=exchange",
    "general": f"convos:general:v2:min={MIN_CHUNK_SIZE}:extractor=general",
}


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


@dataclass
class ConvoProcessResult:
    status: str
    drawers: int = 0
    cleared: int = 0
    room_counts: dict = field(default_factory=dict)
    error: str = ""


def build_source_signature(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def convo_pipeline_fingerprint(extract_mode: str) -> str:
    return CONVO_PIPELINE_FINGERPRINTS.get(extract_mode, f"convos:{extract_mode}:v2")


def build_drawer_id(
    wing: str, room: str, source_file: str, chunk_index: int, extract_mode: str
) -> str:
    digest = hashlib.md5(
        f"{source_file}:{extract_mode}:{chunk_index}".encode()
    ).hexdigest()[:16]
    return f"drawer_{wing}_{room}_{extract_mode}_{digest}"


def namespace_is_current(existing_rows: list, new_rows: list, source_signature: str) -> bool:
    if not existing_rows or not new_rows:
        return False

    existing_ids = [row["id"] for row in existing_rows]
    new_ids = [row["id"] for row in new_rows]
    if len(existing_ids) != len(new_ids):
        return False
    if set(existing_ids) != set(new_ids):
        return False

    pipeline_fingerprint = new_rows[0]["metadata"]["pipeline_fingerprint"]
    for row in existing_rows:
        metadata = row["metadata"]
        if metadata.get("source_signature") != source_signature:
            return False
        if metadata.get("pipeline_fingerprint") != pipeline_fingerprint:
            return False

    return True


def prepare_drawer_rows(
    namespace: DrawerNamespace,
    source_root: str,
    source_signature: str,
    chunks: list,
    agent: str,
) -> list:
    pipeline_fingerprint = convo_pipeline_fingerprint(namespace.extract_mode or "exchange")
    filed_at = datetime.now().isoformat()
    rows = []
    for chunk in chunks:
        room = chunk["room"]
        rows.append(
            {
                "id": build_drawer_id(
                    wing=namespace.wing,
                    room=room,
                    source_file=namespace.source_file,
                    chunk_index=chunk["chunk_index"],
                    extract_mode=namespace.extract_mode or "exchange",
                ),
                "document": chunk["content"],
                "metadata": {
                    "wing": namespace.wing,
                    "room": room,
                    "source_file": namespace.source_file,
                    "source_root": source_root,
                    "source_signature": source_signature,
                    "pipeline_fingerprint": pipeline_fingerprint,
                    "chunk_index": chunk["chunk_index"],
                    "added_by": agent,
                    "filed_at": filed_at,
                    "ingest_mode": namespace.ingest_mode,
                    "extract_mode": namespace.extract_mode,
                    REFRESH_OWNER_KEY: namespace.refresh_owner,
                },
            }
        )
    return rows


def build_exchange_chunks(segments: list[str]) -> list:
    chunks = []
    for segment in segments:
        if not segment or len(segment.strip()) < MIN_CHUNK_SIZE:
            continue

        room = detect_convo_room(segment)
        for raw_chunk in chunk_exchanges(segment):
            chunks.append(
                {
                    "content": raw_chunk["content"],
                    "chunk_index": len(chunks),
                    "room": room,
                }
            )

    return chunks


def process_convo_file(
    filepath: Path,
    source_root: Path,
    store: DrawerStore,
    wing: str,
    agent: str,
    dry_run: bool,
    extract_mode: str,
) -> ConvoProcessResult:
    source_file = str(filepath)
    namespace = DrawerNamespace(
        wing=wing,
        source_file=source_file,
        ingest_mode="convos",
        extract_mode=extract_mode,
    )

    try:
        existing_rows = store.get_namespace_rows(namespace)
    except Exception:
        existing_rows = []

    try:
        segments = normalize_segments(str(filepath))
    except Exception as exc:
        return ConvoProcessResult(status="error", error=str(exc))

    content = join_normalized_segments(segments)
    if not content or len(content.strip()) < MIN_CHUNK_SIZE:
        if not existing_rows:
            return ConvoProcessResult(status="ignored")
        if dry_run:
            return ConvoProcessResult(status="cleared", cleared=len(existing_rows))
        try:
            store.delete_ids([row["id"] for row in existing_rows])
        except Exception as exc:
            return ConvoProcessResult(status="error", error=str(exc))
        return ConvoProcessResult(status="cleared", cleared=len(existing_rows))

    if extract_mode == "general":
        from .general_extractor import extract_memories

        raw_chunks = extract_memories(content)
        chunks = [
            {
                "content": chunk["content"],
                "chunk_index": chunk["chunk_index"],
                "room": chunk.get("memory_type", "general"),
            }
            for chunk in raw_chunks
        ]
    else:
        chunks = build_exchange_chunks(segments)

    if not chunks:
        if not existing_rows:
            return ConvoProcessResult(status="ignored")
        if dry_run:
            return ConvoProcessResult(status="cleared", cleared=len(existing_rows))
        try:
            store.delete_ids([row["id"] for row in existing_rows])
        except Exception as exc:
            return ConvoProcessResult(status="error", error=str(exc))
        return ConvoProcessResult(status="cleared", cleared=len(existing_rows))

    source_signature = build_source_signature(content)
    new_rows = prepare_drawer_rows(
        namespace=namespace,
        source_root=str(source_root),
        source_signature=source_signature,
        chunks=chunks,
        agent=agent,
    )

    if namespace_is_current(existing_rows, new_rows, source_signature):
        return ConvoProcessResult(status="unchanged")

    room_counts = defaultdict(int)
    for chunk in chunks:
        room_counts[chunk["room"]] += 1

    if dry_run:
        status = "new" if not existing_rows else "updated"
        return ConvoProcessResult(status=status, drawers=len(new_rows), room_counts=dict(room_counts))

    try:
        store.upsert_rows(new_rows)
        new_ids = {row["id"] for row in new_rows}
        stale_ids = [row["id"] for row in existing_rows if row["id"] not in new_ids]
        if stale_ids:
            store.delete_ids(stale_ids)
    except Exception as exc:
        return ConvoProcessResult(status="error", error=str(exc))

    status = "new" if not existing_rows else "updated"
    return ConvoProcessResult(status=status, drawers=len(new_rows), room_counts=dict(room_counts))


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
            filepath = Path(root) / filename
            if filepath.suffix.lower() in CONVO_EXTENSIONS:
                files.append(filepath)
    return files


# =============================================================================
# MINE CONVERSATIONS
# =============================================================================


def mine_convos(
    convo_dir: str,
    palace_path: str = None,
    collection_name: str = None,
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
    store = DrawerStore(palace_path=palace_path, collection_name=collection_name)
    print(f"  Palace:  {store.palace_path}")
    if dry_run:
        print("  DRY RUN — nothing will be filed")
    print(f"{'─' * 55}\n")

    total_drawers = 0
    total_cleared = 0
    status_counts = defaultdict(int)
    room_counts = defaultdict(int)

    for i, filepath in enumerate(files, 1):
        result = process_convo_file(
            filepath=filepath,
            source_root=convo_path,
            store=store,
            wing=wing,
            agent=agent,
            dry_run=dry_run,
            extract_mode=extract_mode,
        )
        status_counts[result.status] += 1
        total_drawers += result.drawers
        total_cleared += result.cleared
        for room, count in result.room_counts.items():
            room_counts[room] += count

        if dry_run:
            detail = []
            if result.drawers:
                detail.append(f"{result.drawers} drawers")
            if result.cleared:
                detail.append(f"clear {result.cleared}")
            suffix = f" ({', '.join(detail)})" if detail else ""
            print(f"    [DRY RUN] {filepath.name} → {result.status}{suffix}")
            continue

        if result.status in ("new", "updated"):
            print(f"  ✓ [{i:4}/{len(files)}] {filepath.name[:50]:50} {result.status:7} +{result.drawers}")
        elif result.status == "cleared":
            print(f"  ✓ [{i:4}/{len(files)}] {filepath.name[:50]:50} cleared  -{result.cleared}")
        elif result.status == "error":
            print(f"  ! [{i:4}/{len(files)}] {filepath.name[:50]:50} error    {result.error}")

    print(f"\n{'=' * 55}")
    print("  Done.")
    print(f"  Files scanned: {len(files)}")
    print(f"  Files new: {status_counts['new']}")
    print(f"  Files updated: {status_counts['updated']}")
    print(f"  Files unchanged: {status_counts['unchanged']}")
    print(f"  Files cleared: {status_counts['cleared']}")
    print(f"  Files errored: {status_counts['error']}")
    if status_counts["ignored"]:
        print(f"  Files ignored (no usable content): {status_counts['ignored']}")
    print(f"  Drawers filed: {total_drawers}")
    print(f"  Drawers cleared: {total_cleared}")
    if room_counts:
        print("\n  Drawers filed by room:")
        for room, count in sorted(room_counts.items(), key=lambda x: x[1], reverse=True):
            print(f"    {room:20} {count} drawers")
    print('\n  Next: mempalace search "what you\'re looking for"')
    print(f"{'=' * 55}\n")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python convo_miner.py <convo_dir> [--palace PATH] [--limit N] [--dry-run]")
        sys.exit(1)

    mine_convos(sys.argv[1])
