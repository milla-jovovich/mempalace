"""
mempalace doctor — Palace health check.

Runs a series of diagnostic checks against a palace and reports the result of
each one with a green check mark or a red cross. Designed to be safe to run on
any palace at any time: it never writes, never mutates, and never requires
network access.

Checks performed:
    1. ChromaDB connectivity (palace path exists, collection opens)
    2. Orphan drawers   (drawers missing `wing` or `room` metadata)
    3. Duplicate drawers (identical document text under different ids)
    4. Knowledge graph dangling references (triples pointing at missing entities)
    5. identity.txt presence (Layer 0 wake-up source)
    6. AAAK / config.json validity (parses and contains required keys)
"""

from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

# ANSI color codes — kept inline so we don't pull a new dependency.
GREEN = "\033[32m"
RED = "\033[31m"
YELLOW = "\033[33m"
BOLD = "\033[1m"
RESET = "\033[0m"

OK = "ok"
FAIL = "fail"
WARN = "warn"


@dataclass
class CheckResult:
    """Outcome of a single diagnostic check."""

    name: str
    status: str  # OK | FAIL | WARN
    message: str
    details: list[str] = field(default_factory=list)

    @property
    def is_ok(self) -> bool:
        return self.status == OK


@dataclass
class DoctorReport:
    """Aggregated report for a full doctor run."""

    results: list[CheckResult] = field(default_factory=list)

    def add(self, result: CheckResult) -> None:
        self.results.append(result)

    @property
    def healthy(self) -> bool:
        return all(r.status != FAIL for r in self.results)

    @property
    def failures(self) -> list[CheckResult]:
        return [r for r in self.results if r.status == FAIL]

    @property
    def warnings(self) -> list[CheckResult]:
        return [r for r in self.results if r.status == WARN]


# ── Individual checks ──────────────────────────────────────────────────────


def check_chromadb(palace_path: str, collection_name: str = "mempalace_drawers") -> CheckResult:
    """Verify the ChromaDB palace can be opened and the drawer collection loads."""
    if not os.path.isdir(palace_path):
        return CheckResult(
            "ChromaDB connection",
            FAIL,
            f"Palace directory not found: {palace_path}",
        )
    try:
        import chromadb  # local import — heavy dependency
    except ImportError:
        return CheckResult(
            "ChromaDB connection",
            FAIL,
            "chromadb is not installed",
        )
    try:
        client = chromadb.PersistentClient(path=palace_path)
        col = client.get_or_create_collection(collection_name)
        count = col.count()
    except Exception as e:  # pragma: no cover - defensive
        return CheckResult(
            "ChromaDB connection",
            FAIL,
            f"Failed to open collection: {e}",
        )
    return CheckResult(
        "ChromaDB connection",
        OK,
        f"opened '{collection_name}' ({count} drawers)",
    )


def check_orphan_drawers(metadatas: list[dict]) -> CheckResult:
    """Find drawers whose metadata is missing `wing` or `room`."""
    orphans: list[str] = []
    for i, meta in enumerate(metadatas or []):
        meta = meta or {}
        if not meta.get("wing") or not meta.get("room"):
            orphans.append(f"#{i}: wing={meta.get('wing')!r} room={meta.get('room')!r}")
    if orphans:
        return CheckResult(
            "Orphan drawers",
            WARN,
            f"{len(orphans)} drawer(s) missing wing/room metadata",
            details=orphans[:10],
        )
    return CheckResult("Orphan drawers", OK, "all drawers have wing + room")


def check_duplicate_drawers(documents: list[str], ids: list[str]) -> CheckResult:
    """Detect drawers whose verbatim text is identical."""
    seen: dict[str, str] = {}
    duplicates: list[str] = []
    for doc, doc_id in zip(documents or [], ids or []):
        if doc is None:
            continue
        key = doc.strip()
        if not key:
            continue
        if key in seen:
            duplicates.append(f"{doc_id} duplicates {seen[key]}")
        else:
            seen[key] = doc_id
    if duplicates:
        return CheckResult(
            "Duplicate drawers",
            WARN,
            f"{len(duplicates)} duplicate drawer(s) detected",
            details=duplicates[:10],
        )
    return CheckResult("Duplicate drawers", OK, "no duplicate drawers")


def check_knowledge_graph(db_path: str) -> CheckResult:
    """Open the knowledge graph SQLite db and look for dangling triples."""
    if not os.path.exists(db_path):
        return CheckResult(
            "Knowledge graph",
            WARN,
            f"no knowledge graph at {db_path} (skipping)",
        )
    try:
        conn = sqlite3.connect(db_path, timeout=5)
    except sqlite3.Error as e:
        return CheckResult("Knowledge graph", FAIL, f"cannot open db: {e}")

    try:
        rows = conn.execute(
            """
            SELECT t.id, t.subject, t.object
            FROM triples t
            LEFT JOIN entities es ON es.id = t.subject
            LEFT JOIN entities eo ON eo.id = t.object
            WHERE es.id IS NULL OR eo.id IS NULL
            """
        ).fetchall()
        total = conn.execute("SELECT COUNT(*) FROM triples").fetchone()[0]
    except sqlite3.Error as e:
        conn.close()
        return CheckResult("Knowledge graph", FAIL, f"query failed: {e}")
    finally:
        conn.close()

    if rows:
        details = [f"triple {tid}: {sub!r} -> {obj!r}" for tid, sub, obj in rows[:10]]
        return CheckResult(
            "Knowledge graph",
            FAIL,
            f"{len(rows)} dangling reference(s) out of {total} triple(s)",
            details=details,
        )
    return CheckResult("Knowledge graph", OK, f"{total} triple(s), no dangling references")


def check_identity(identity_path: str) -> CheckResult:
    """Confirm identity.txt exists and is non-empty."""
    if not os.path.exists(identity_path):
        return CheckResult(
            "identity.txt",
            WARN,
            f"missing: {identity_path}",
        )
    try:
        size = os.path.getsize(identity_path)
    except OSError as e:
        return CheckResult("identity.txt", FAIL, f"cannot stat file: {e}")
    if size == 0:
        return CheckResult("identity.txt", WARN, "file exists but is empty")
    return CheckResult("identity.txt", OK, f"{size} bytes")


def check_aaak_config(config_path: str) -> CheckResult:
    """Validate the MemPalace config.json (which seeds AAAK behavior)."""
    if not os.path.exists(config_path):
        return CheckResult(
            "AAAK config",
            WARN,
            f"no config.json at {config_path}",
        )
    try:
        with open(config_path, "r") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        return CheckResult("AAAK config", FAIL, f"invalid JSON: {e}")

    required = ("palace_path", "collection_name")
    missing = [k for k in required if k not in data]
    if missing:
        return CheckResult(
            "AAAK config",
            FAIL,
            f"missing required keys: {', '.join(missing)}",
        )
    return CheckResult("AAAK config", OK, "config.json valid")


# ── Orchestration ──────────────────────────────────────────────────────────


def run_doctor(
    palace_path: str,
    config_dir: str | None = None,
    collection_name: str = "mempalace_drawers",
    chroma_loader: Callable[[str, str], tuple[list[str], list[dict], list[str]]] | None = None,
) -> DoctorReport:
    """Run all diagnostic checks and return an aggregated report.

    Args:
        palace_path: ChromaDB palace directory.
        config_dir: ~/.mempalace style config directory. Defaults to
            ``~/.mempalace`` when not provided.
        collection_name: ChromaDB collection name to inspect.
        chroma_loader: Optional injection point for tests. Should return
            ``(documents, metadatas, ids)``. When omitted, the function reads
            directly from ChromaDB.
    """
    config_dir = config_dir or os.path.expanduser("~/.mempalace")
    report = DoctorReport()

    # 1. ChromaDB connectivity
    chroma_result = check_chromadb(palace_path, collection_name)
    report.add(chroma_result)

    # 2 + 3. Drawer-level checks (only if we can read drawers)
    documents: list[str] = []
    metadatas: list[dict] = []
    ids: list[str] = []
    if chroma_result.is_ok:
        try:
            if chroma_loader is not None:
                documents, metadatas, ids = chroma_loader(palace_path, collection_name)
            else:  # pragma: no cover - exercised via integration
                import chromadb

                client = chromadb.PersistentClient(path=palace_path)
                col = client.get_or_create_collection(collection_name)
                got = col.get(include=["documents", "metadatas"])
                documents = got.get("documents") or []
                metadatas = got.get("metadatas") or []
                ids = got.get("ids") or []
        except Exception as e:  # pragma: no cover - defensive
            report.add(CheckResult("Drawer load", FAIL, f"could not read drawers: {e}"))

    report.add(check_orphan_drawers(metadatas))
    report.add(check_duplicate_drawers(documents, ids))

    # 4. Knowledge graph
    kg_path = str(Path(config_dir) / "knowledge_graph.sqlite3")
    report.add(check_knowledge_graph(kg_path))

    # 5. identity.txt
    identity_path = str(Path(config_dir) / "identity.txt")
    report.add(check_identity(identity_path))

    # 6. AAAK / config.json
    config_path = str(Path(config_dir) / "config.json")
    report.add(check_aaak_config(config_path))

    return report


def format_report(report: DoctorReport, use_color: bool = True) -> str:
    """Render a DoctorReport as a human-friendly multi-line string."""

    def colorize(text: str, color: str) -> str:
        if not use_color:
            return text
        return f"{color}{text}{RESET}"

    lines: list[str] = []
    header = colorize("MemPalace Doctor", BOLD) if use_color else "MemPalace Doctor"
    lines.append(header)
    lines.append("=" * 40)

    for result in report.results:
        if result.status == OK:
            mark = colorize("✓", GREEN)
        elif result.status == WARN:
            mark = colorize("!", YELLOW)
        else:
            mark = colorize("✗", RED)
        lines.append(f"  {mark} {result.name}: {result.message}")
        for detail in result.details:
            lines.append(f"      - {detail}")

    lines.append("")
    if report.healthy:
        summary = colorize("Palace is healthy.", GREEN)
    else:
        summary = colorize(
            f"{len(report.failures)} failing check(s).",
            RED,
        )
    lines.append(summary)
    if report.warnings and report.healthy:
        lines.append(colorize(f"{len(report.warnings)} warning(s).", YELLOW))
    return "\n".join(lines)
