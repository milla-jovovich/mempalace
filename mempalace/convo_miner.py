#!/usr/bin/env python3
"""
convo_miner.py — Mine conversations into the palace.

Ingests chat exports (Claude Code, ChatGPT, Slack, plain text transcripts).
Normalizes format, chunks by exchange pair (Q+A = one unit), files to palace.

Same palace as project mining. Different ingest strategy.
"""

import json
import os
import re
import sys
import hashlib
from pathlib import Path
from datetime import datetime
from collections import defaultdict

import chromadb

from .normalize import normalize


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
    "tool-results",
    "memory",
}

MIN_CHUNK_SIZE = 30


# =============================================================================
# WING DETECTION — 3-tier auto-detect project from conversations
# =============================================================================

# Anchors: common parent directories that sit above project folders.
_PATH_ANCHORS = {"projects", "developer", "code", "repos", "src", "workspace"}

# Regex for project directory references inside conversation text.
_PROJECT_PATH_RE = re.compile(
    r"(?:^|[\s\"'(])"           # boundary before the path
    r"/(?:Users|home)/[^/]+/"   # home directory
    r"(?:[Pp]rojects|[Dd]eveloper|code|repos|src|workspace)/"  # anchor dir
    r"([a-zA-Z0-9][a-zA-Z0-9._-]{1,50})"  # project name (capture group)
)


def detect_wing(filepath: str, convo_dir: str, content: str = None,
                 raw_content: str = None) -> str:
    """Infer the wing (project) name from a conversation file.

    Uses a 3-tier detection strategy:

    1. **Path-based** — Claude Code encodes project paths in directory names.
       e.g., ``-Users-name-Projects-myapp`` → ``myapp``.

    2. **JSONL cwd-based** — Claude Code JSONL entries contain a ``cwd`` field
       recording the agent's working directory. The most-referenced project
       directory (excluding the bare anchor) is used as the wing.

    3. **Content-based** — Scan conversation text for project directory paths
       like ``/Users/name/Projects/myapp/src/...``. The most-referenced project
       name wins.

    Falls back to ``"general"`` when no project can be determined.

    Pass ``raw_content`` to avoid a redundant file read when the caller has
    already loaded the file (e.g., ``mine_convos``).
    """
    # Tier 1: path-based
    wing = _detect_wing_from_path(filepath, convo_dir)
    if wing != "general":
        return wing

    # Tier 2: JSONL cwd field (needs raw file, not normalized transcript)
    if raw_content is None:
        try:
            with open(filepath, "r", encoding="utf-8", errors="replace") as f:
                raw_content = f.read()
        except OSError:
            raw_content = ""

    if raw_content:
        wing = _detect_wing_from_cwd(raw_content)
        if wing != "general":
            return wing

    # Tier 3: content path references (works on either raw or normalized)
    search_text = raw_content or content or ""
    wing = _detect_wing_from_content(search_text)
    if wing != "general":
        return wing

    return "general"


# Keep the old name as an alias for backwards compatibility and tests.
detect_wing_from_path = detect_wing


def _detect_wing_from_path(filepath: str, convo_dir: str) -> str:
    """Tier 1: infer wing from the encoded project directory in the file path."""
    filepath_str = str(filepath)
    convo_dir_resolved = str(Path(convo_dir).expanduser().resolve())

    if not filepath_str.startswith(convo_dir_resolved):
        # Not under the convo dir — use parent directory name
        parent = Path(filepath).parent.name
        if parent:
            return _clean_wing(parent)
        return "general"

    relative = filepath_str[len(convo_dir_resolved):].lstrip(os.sep)
    project_dir = relative.split(os.sep)[0] if os.sep in relative else ""
    if not project_dir:
        return "general"

    # Claude Code encoded paths: -Users-name-Projects-myapp
    segments = [s for s in project_dir.split("-") if s]
    for i, seg in enumerate(segments):
        if seg.lower() in _PATH_ANCHORS:
            remaining = segments[i + 1:]
            if remaining:
                return _clean_wing("-".join(remaining))
            return "general"

    # No anchor found — likely a home directory or other non-project path
    return "general"


def _detect_wing_from_cwd(content: str) -> str:
    """Tier 2: extract project from cwd fields in Claude Code JSONL entries."""
    # Only parse JSONL — skip if content doesn't look like it
    if not content.strip().startswith("{"):
        return "general"

    project_counts = {}
    for line in content.split("\n"):
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        if not isinstance(entry, dict):
            continue

        cwd = entry.get("cwd", "")
        if not cwd:
            continue

        # Extract project name from cwd path
        proj = _project_from_path(cwd)
        if proj:
            project_counts[proj] = project_counts.get(proj, 0) + 1

    if project_counts:
        return _clean_wing(max(project_counts, key=project_counts.get))
    return "general"


def _detect_wing_from_content(content: str) -> str:
    """Tier 3: scan conversation text for project directory references."""
    project_counts = {}
    for match in _PROJECT_PATH_RE.finditer(content[:50000]):
        proj = match.group(1)
        if proj and len(proj) > 2:
            project_counts[proj] = project_counts.get(proj, 0) + 1

    if project_counts:
        return _clean_wing(max(project_counts, key=project_counts.get))
    return "general"


def _project_from_path(path: str) -> str:
    """Extract project name from an absolute path, or return empty string."""
    parts = path.replace("\\", "/").split("/")
    for i, part in enumerate(parts):
        if part.lower() in _PATH_ANCHORS and i + 1 < len(parts):
            candidate = parts[i + 1]
            if candidate and len(candidate) > 1:
                return candidate
    return ""


def _clean_wing(name: str) -> str:
    """Normalize a project name into a valid wing name."""
    return name.lower().replace("-", "_").replace(".", "_").replace(" ", "_").strip("_")


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


def get_collection(palace_path: str):
    os.makedirs(palace_path, exist_ok=True)
    client = chromadb.PersistentClient(path=palace_path)
    try:
        return client.get_collection("mempalace_drawers")
    except Exception:
        return client.create_collection("mempalace_drawers")


def file_already_mined(collection, source_file: str) -> bool:
    try:
        results = collection.get(where={"source_file": source_file}, limit=1)
        return len(results.get("ids", [])) > 0
    except Exception:
        return False


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
                files.append(filepath)
    return files


# =============================================================================
# MINE CONVERSATIONS
# =============================================================================


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
    auto_wing = wing is None
    if not wing:
        wing = convo_path.name.lower().replace(" ", "_").replace("-", "_")

    files = scan_convos(convo_dir)
    if limit > 0:
        files = files[:limit]

    print(f"\n{'=' * 55}")
    print("  MemPalace Mine — Conversations")
    print(f"{'=' * 55}")
    if auto_wing:
        print("  Wing:    (auto-detect per file)")
    else:
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

    wing_counts = defaultdict(int)

    for i, filepath in enumerate(files, 1):
        source_file = str(filepath)

        # Skip if already filed
        if not dry_run and file_already_mined(collection, source_file):
            files_skipped += 1
            continue

        # Read raw content once — shared by normalize and detect_wing
        try:
            with open(filepath, "r", encoding="utf-8", errors="replace") as f:
                raw_content = f.read()
        except OSError:
            continue

        # Normalize format
        try:
            content = normalize(str(filepath))
        except (OSError, ValueError):
            continue

        if not content or len(content.strip()) < MIN_CHUNK_SIZE:
            continue

        # Auto-detect wing from file path + content when no explicit --wing given
        file_wing = wing
        if auto_wing:
            file_wing = detect_wing(filepath, str(convo_path), content,
                                    raw_content=raw_content)

        # Chunk — either exchange pairs or general extraction
        if extract_mode == "general":
            from .general_extractor import extract_memories

            chunks = extract_memories(content)
            # Each chunk already has memory_type; use it as the room name
        else:
            chunks = chunk_exchanges(content)

        if not chunks:
            continue

        # Detect room from content (general mode uses memory_type instead)
        if extract_mode != "general":
            room = detect_convo_room(content)
        else:
            room = None  # set per-chunk below

        wing_counts[file_wing] = wing_counts.get(file_wing, 0) + 1

        if dry_run:
            if extract_mode == "general":
                from collections import Counter

                type_counts = Counter(c.get("memory_type", "general") for c in chunks)
                types_str = ", ".join(f"{t}:{n}" for t, n in type_counts.most_common())
                print(
                    f"    [DRY RUN] {filepath.name} → wing:{file_wing} "
                    f"{len(chunks)} memories ({types_str})"
                )
            else:
                print(
                    f"    [DRY RUN] {filepath.name} → wing:{file_wing} "
                    f"room:{room} ({len(chunks)} drawers)"
                )
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

        # File each chunk
        drawers_added = 0
        for chunk in chunks:
            chunk_room = chunk.get("memory_type", room) if extract_mode == "general" else room
            if extract_mode == "general":
                room_counts[chunk_room] += 1
            drawer_id = (
                f"drawer_{file_wing}_{chunk_room}_"
                f"{hashlib.md5((source_file + str(chunk['chunk_index'])).encode(), usedforsecurity=False).hexdigest()[:16]}"
            )
            try:
                collection.add(
                    documents=[chunk["content"]],
                    ids=[drawer_id],
                    metadatas=[
                        {
                            "wing": file_wing,
                            "room": chunk_room,
                            "source_file": source_file,
                            "chunk_index": chunk["chunk_index"],
                            "added_by": agent,
                            "filed_at": datetime.now().isoformat(),
                            "ingest_mode": "convos",
                            "extract_mode": extract_mode,
                        }
                    ],
                )
                drawers_added += 1
            except Exception as e:
                if "already exists" not in str(e).lower():
                    raise

        total_drawers += drawers_added
        wing_label = f" [{file_wing}]" if auto_wing else ""
        print(f"  ✓ [{i:4}/{len(files)}] {filepath.name[:50]:50} +{drawers_added}{wing_label}")

    print(f"\n{'=' * 55}")
    print("  Done.")
    print(f"  Files processed: {len(files) - files_skipped}")
    print(f"  Files skipped (already filed): {files_skipped}")
    print(f"  Drawers filed: {total_drawers}")
    if wing_counts and auto_wing:
        print("\n  By wing:")
        for w, count in sorted(wing_counts.items(), key=lambda x: x[1], reverse=True):
            print(f"    {w:20} {count} files")
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
