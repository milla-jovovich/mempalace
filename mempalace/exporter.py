"""
exporter.py — Export, import, and backup palace data.
======================================================

Three workflows for protecting palace data:

  1. Single JSON export — drawers + KG in one portable file (default)
     Best for: full backup with KG, MCP-driven workflows
     mempalace export backup.json

  2. JSONL per wing/room — git-friendly directory layout
     Best for: cross-device sync via git, incremental updates
     mempalace export ~/.mempalace/sync/ --format jsonl

  3. Binary backup — fast directory copy or zip archive
     Best for: rapid local snapshots, fast restore (no re-embedding)
     mempalace backup
     mempalace backup --zip

The format is auto-detected on import:
  - .json file → single-file format
  - directory  → JSONL per wing/room

Zero API calls. Zero new dependencies. Hybrid design developed jointly
with @scokeepa (PR #453).

The single-JSON format is self-describing:

    {
        "format": "mempalace_export",
        "version": 1,
        "exported_at": "2026-04-09T...",
        "drawers": [...],
        "kg_entities": [...],
        "kg_triples": [...]
    }
"""

import json
import logging
import os
import shutil
import sqlite3 as sqlite3_mod
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import List, Optional

import chromadb

from mempalace.knowledge_graph import KnowledgeGraph

logger = logging.getLogger("mempalace")

EXPORT_FORMAT = "mempalace_export"
EXPORT_VERSION = 1


# ── Result types ─────────────────────────────────────────────────────


@dataclass
class ExportResult:
    """Result of a palace export operation."""

    success: bool = False
    output_file: str = ""
    drawers_exported: int = 0
    kg_entities_exported: int = 0
    kg_triples_exported: int = 0
    errors: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "output_file": self.output_file,
            "drawers_exported": self.drawers_exported,
            "kg_entities_exported": self.kg_entities_exported,
            "kg_triples_exported": self.kg_triples_exported,
            "errors": self.errors[:10],
        }


@dataclass
class ImportResult:
    """Result of a palace import operation."""

    success: bool = False
    drawers_imported: int = 0
    drawers_skipped: int = 0
    kg_entities_imported: int = 0
    kg_triples_imported: int = 0
    errors: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "drawers_imported": self.drawers_imported,
            "drawers_skipped": self.drawers_skipped,
            "kg_entities_imported": self.kg_entities_imported,
            "kg_triples_imported": self.kg_triples_imported,
            "errors": self.errors[:10],
        }


# ── Export ───────────────────────────────────────────────────────────


def _read_all_drawers(palace_path: str) -> List[dict]:
    """Read all drawers from ChromaDB in batches."""
    try:
        client = chromadb.PersistentClient(path=palace_path)
        col = client.get_collection("mempalace_drawers")
    except Exception as e:
        logger.warning("No palace collection found: %s", e)
        return []

    drawers = []
    batch_size = 500
    offset = 0

    while True:
        try:
            batch = col.get(
                include=["documents", "metadatas"],
                limit=batch_size,
                offset=offset,
            )
        except Exception:
            break

        ids = batch.get("ids", [])
        docs = batch.get("documents", [])
        metas = batch.get("metadatas", [])

        if not ids:
            break

        for drawer_id, doc, meta in zip(ids, docs, metas):
            drawers.append({
                "id": drawer_id,
                "document": doc,
                "metadata": meta,
            })

        offset += len(ids)

    return drawers


def _read_all_kg(kg: KnowledgeGraph) -> tuple:
    """Read all entities and triples from the knowledge graph."""
    conn = kg._conn()

    entities = []
    for row in conn.execute("SELECT * FROM entities").fetchall():
        entities.append({
            "id": row["id"],
            "name": row["name"],
            "type": row["type"],
            "properties": row["properties"],
        })

    triples = []
    for row in conn.execute(
        """SELECT t.*, s.name as sub_name, o.name as obj_name
           FROM triples t
           JOIN entities s ON t.subject = s.id
           JOIN entities o ON t.object = o.id"""
    ).fetchall():
        triples.append({
            "id": row["id"],
            "subject": row["sub_name"],
            "subject_id": row["subject"],
            "predicate": row["predicate"],
            "object": row["obj_name"],
            "object_id": row["object"],
            "valid_from": row["valid_from"],
            "valid_to": row["valid_to"],
            "confidence": row["confidence"],
            "source_closet": row["source_closet"],
            "source_file": row["source_file"],
        })

    return entities, triples


def export_palace(
    palace_path: str,
    output_file: str,
    kg: Optional[KnowledgeGraph] = None,
) -> ExportResult:
    """Export all palace data to a JSON file.

    Args:
        palace_path: Path to the palace ChromaDB directory.
        output_file: Path for the output JSON file.
        kg: KnowledgeGraph instance (creates from palace_path if None).

    Returns:
        ExportResult with export stats.
    """
    result = ExportResult(output_file=output_file)

    # Read drawers
    drawers = _read_all_drawers(palace_path)
    result.drawers_exported = len(drawers)

    # Read KG
    if kg is None:
        kg_path = os.path.join(palace_path, "knowledge_graph.sqlite3")
        if os.path.exists(kg_path):
            kg = KnowledgeGraph(db_path=kg_path)
        else:
            kg = None

    entities, triples = [], []
    if kg is not None:
        try:
            entities, triples = _read_all_kg(kg)
            result.kg_entities_exported = len(entities)
            result.kg_triples_exported = len(triples)
        except Exception as e:
            result.errors.append(f"KG read error: {e}")

    # Build export document
    export_data = {
        "format": EXPORT_FORMAT,
        "version": EXPORT_VERSION,
        "exported_at": datetime.now().isoformat(),
        "palace_path": palace_path,
        "drawers": drawers,
        "kg_entities": entities,
        "kg_triples": triples,
    }

    # Write to file
    try:
        output_dir = os.path.dirname(output_file)
        if output_dir:
            os.makedirs(output_dir, exist_ok=True)
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(export_data, f, indent=2, ensure_ascii=False)
        result.success = True
    except Exception as e:
        result.errors.append(f"Write error: {e}")

    if result.success:
        logger.info(
            "Note: embeddings are not included. "
            "Import will re-embed using the configured model."
        )

    return result


# ── Import ───────────────────────────────────────────────────────────


def import_palace(
    input_file: str,
    palace_path: str,
    kg: Optional[KnowledgeGraph] = None,
    skip_existing: bool = True,
) -> ImportResult:
    """Import palace data from a JSON export file.

    Args:
        input_file: Path to the JSON export file.
        palace_path: Path to the target palace directory.
        kg: KnowledgeGraph instance (creates from palace_path if None).
        skip_existing: If True, skip drawers that already exist (by ID).

    Returns:
        ImportResult with import stats.
    """
    result = ImportResult()

    # Read export file
    try:
        with open(input_file, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        result.errors.append(f"Read error: {e}")
        return result

    # Validate format
    if data.get("format") != EXPORT_FORMAT:
        result.errors.append(
            f"Unknown format: {data.get('format')}. Expected: {EXPORT_FORMAT}"
        )
        return result

    if data.get("version", 0) > EXPORT_VERSION:
        result.errors.append(
            f"Export version {data.get('version')} is newer than supported ({EXPORT_VERSION})"
        )
        return result

    # Import drawers
    drawers = data.get("drawers", [])
    if drawers:
        try:
            os.makedirs(palace_path, exist_ok=True)
            client = chromadb.PersistentClient(path=palace_path)
            try:
                col = client.get_collection("mempalace_drawers")
            except Exception:
                col = client.create_collection("mempalace_drawers")

            # Get existing IDs to skip duplicates
            existing_ids = set()
            if skip_existing:
                offset = 0
                while True:
                    try:
                        batch = col.get(limit=500, offset=offset)
                        batch_ids = batch.get("ids", [])
                        if not batch_ids:
                            break
                        existing_ids.update(batch_ids)
                        offset += len(batch_ids)
                    except Exception:
                        break

            # Add drawers in batches
            batch_ids, batch_docs, batch_metas = [], [], []
            for drawer in drawers:
                drawer_id = drawer["id"]
                if skip_existing and drawer_id in existing_ids:
                    result.drawers_skipped += 1
                    continue

                batch_ids.append(drawer_id)
                batch_docs.append(drawer["document"])
                batch_metas.append(drawer["metadata"])

                if len(batch_ids) >= 100:
                    col.add(ids=batch_ids, documents=batch_docs, metadatas=batch_metas)
                    result.drawers_imported += len(batch_ids)
                    batch_ids, batch_docs, batch_metas = [], [], []

            if batch_ids:
                col.add(ids=batch_ids, documents=batch_docs, metadatas=batch_metas)
                result.drawers_imported += len(batch_ids)

        except Exception as e:
            result.errors.append(f"Drawer import error: {e}")

    # Import KG
    kg_entities = data.get("kg_entities", [])
    kg_triples = data.get("kg_triples", [])

    if kg_entities or kg_triples:
        if kg is None:
            kg_path = os.path.join(palace_path, "knowledge_graph.sqlite3")
            kg = KnowledgeGraph(db_path=kg_path)

        for entity in kg_entities:
            try:
                props = entity.get("properties", "{}")
                if isinstance(props, str):
                    props = json.loads(props)
                kg.add_entity(
                    entity["name"],
                    entity_type=entity.get("type", "unknown"),
                    properties=props,
                )
                result.kg_entities_imported += 1
            except Exception as e:
                result.errors.append(f"Entity import error ({entity.get('name')}): {e}")

        # TODO: Triple import uses entity names, which can mislink if two different
        # entities share a name across palaces. ID-based triple import would be safer.
        for triple in kg_triples:
            try:
                kg.add_triple(
                    triple["subject"],
                    triple["predicate"],
                    triple["object"],
                    valid_from=triple.get("valid_from"),
                    valid_to=triple.get("valid_to"),
                    confidence=triple.get("confidence", 1.0),
                    source_closet=triple.get("source_closet"),
                    source_file=triple.get("source_file"),
                )
                result.kg_triples_imported += 1
            except Exception as e:
                result.errors.append(f"Triple import error: {e}")

    result.success = len(result.errors) == 0
    return result


# ── JSONL per wing/room (incorporated from PR #453 by @scokeepa) ─────


def export_palace_jsonl(
    palace_path: str,
    output_dir: str,
    kg: Optional[KnowledgeGraph] = None,
    include_kg: bool = True,
) -> ExportResult:
    """Export drawers as JSONL files organized by wing/room (git-friendly).

    Layout:
        output_dir/
        ├── wing_a/
        │   ├── room1.jsonl
        │   └── room2.jsonl
        └── wing_b/
            └── room3.jsonl
        └── _kg.json   (optional, if include_kg=True)

    Args:
        palace_path: Path to the palace ChromaDB directory.
        output_dir: Directory to write JSONL files to.
        kg: KnowledgeGraph instance (creates from palace_path if None).
        include_kg: If True, also export knowledge graph to _kg.json.

    Returns:
        ExportResult with export stats.
    """
    result = ExportResult(output_file=output_dir)
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    drawers = _read_all_drawers(palace_path)
    result.drawers_exported = len(drawers)

    # Group by wing/room
    groups = {}
    for drawer in drawers:
        meta = drawer.get("metadata", {}) or {}
        wing = meta.get("wing", "unknown")
        room = meta.get("room", "general")
        groups.setdefault((wing, room), []).append(drawer)

    # Write JSONL files
    for (wing, room), wing_drawers in sorted(groups.items()):
        wing_dir = out / wing
        wing_dir.mkdir(parents=True, exist_ok=True)
        filepath = wing_dir / f"{room}.jsonl"
        try:
            with open(filepath, "w", encoding="utf-8") as f:
                for drawer in wing_drawers:
                    f.write(json.dumps(drawer, ensure_ascii=False) + "\n")
        except Exception as e:
            result.errors.append(f"Write error {filepath}: {e}")

    # Export KG to _kg.json alongside drawer files
    if include_kg:
        if kg is None:
            kg_path = os.path.join(palace_path, "knowledge_graph.sqlite3")
            if os.path.exists(kg_path):
                kg = KnowledgeGraph(db_path=kg_path)

        if kg is not None:
            try:
                entities, triples = _read_all_kg(kg)
                result.kg_entities_exported = len(entities)
                result.kg_triples_exported = len(triples)
                kg_doc = {
                    "format": EXPORT_FORMAT,
                    "version": EXPORT_VERSION,
                    "exported_at": datetime.now().isoformat(),
                    "kg_entities": entities,
                    "kg_triples": triples,
                }
                with open(out / "_kg.json", "w", encoding="utf-8") as f:
                    json.dump(kg_doc, f, indent=2, ensure_ascii=False)
            except Exception as e:
                result.errors.append(f"KG export error: {e}")

    result.success = len(result.errors) == 0
    return result


def import_palace_jsonl(
    input_dir: str,
    palace_path: str,
    kg: Optional[KnowledgeGraph] = None,
) -> ImportResult:
    """Import drawers from a JSONL directory layout.

    Args:
        input_dir: Directory containing wing/room.jsonl files.
        palace_path: Path to the target palace directory.
        kg: KnowledgeGraph instance (creates from palace_path if None).

    Returns:
        ImportResult with import stats.
    """
    result = ImportResult()
    inp = Path(input_dir)

    if not inp.exists():
        result.errors.append(f"Import directory not found: {input_dir}")
        return result

    os.makedirs(palace_path, exist_ok=True)
    client = chromadb.PersistentClient(path=palace_path)
    try:
        col = client.get_collection("mempalace_drawers")
    except Exception:
        col = client.create_collection("mempalace_drawers")

    for jsonl_file in sorted(inp.rglob("*.jsonl")):
        drawers = []
        try:
            with open(jsonl_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        drawers.append(json.loads(line))
        except Exception as e:
            result.errors.append(f"Read error {jsonl_file}: {e}")
            continue

        if not drawers:
            continue

        # Dedupe by ID — fetch existing IDs from this batch
        ids = [d["id"] for d in drawers]
        existing = set()
        try:
            existing_result = col.get(ids=ids)
            existing = set(existing_result.get("ids", []))
        except Exception:
            pass

        new_drawers = [d for d in drawers if d["id"] not in existing]
        result.drawers_skipped += len(drawers) - len(new_drawers)

        if new_drawers:
            try:
                # Batch in chunks of 100 to avoid OOM
                for i in range(0, len(new_drawers), 100):
                    chunk = new_drawers[i : i + 100]
                    col.add(
                        ids=[d["id"] for d in chunk],
                        documents=[d["document"] for d in chunk],
                        metadatas=[d["metadata"] for d in chunk],
                    )
                result.drawers_imported += len(new_drawers)
            except Exception as e:
                result.errors.append(f"Add error {jsonl_file}: {e}")

    # Import KG if _kg.json exists alongside the JSONL files
    kg_file = inp / "_kg.json"
    if kg_file.exists():
        try:
            with open(kg_file, "r", encoding="utf-8") as f:
                kg_doc = json.load(f)

            if kg is None:
                kg_path = os.path.join(palace_path, "knowledge_graph.sqlite3")
                kg = KnowledgeGraph(db_path=kg_path)

            for entity in kg_doc.get("kg_entities", []):
                try:
                    props = entity.get("properties", "{}")
                    if isinstance(props, str):
                        props = json.loads(props)
                    kg.add_entity(
                        entity["name"],
                        entity_type=entity.get("type", "unknown"),
                        properties=props,
                    )
                    result.kg_entities_imported += 1
                except Exception as e:
                    result.errors.append(f"KG entity error: {e}")

            for triple in kg_doc.get("kg_triples", []):
                try:
                    kg.add_triple(
                        triple["subject"],
                        triple["predicate"],
                        triple["object"],
                        valid_from=triple.get("valid_from"),
                        valid_to=triple.get("valid_to"),
                        confidence=triple.get("confidence", 1.0),
                        source_closet=triple.get("source_closet"),
                        source_file=triple.get("source_file"),
                    )
                    result.kg_triples_imported += 1
                except Exception as e:
                    result.errors.append(f"KG triple error: {e}")
        except Exception as e:
            result.errors.append(f"KG import error: {e}")

    result.success = len(result.errors) == 0
    return result


# ── Binary backup (incorporated from PR #453 by @scokeepa) ───────────


@dataclass
class BackupResult:
    """Result of a backup operation."""

    success: bool = False
    backup_path: str = ""
    size_bytes: int = 0
    pruned: List[str] = field(default_factory=list)
    validation_errors: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)

    @property
    def size_mb(self) -> float:
        return self.size_bytes / (1024 * 1024)

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "backup_path": self.backup_path,
            "size_bytes": self.size_bytes,
            "size_mb": round(self.size_mb, 2),
            "pruned": self.pruned,
            "validation_errors": self.validation_errors,
            "errors": self.errors[:10],
        }


def _validate_backup(backup_path, zip_mode):
    """Quick integrity check after backup."""
    from pathlib import Path
    errors = []
    try:
        bp = Path(backup_path) if not isinstance(backup_path, Path) else backup_path
        if zip_mode:
            import zipfile as zf_mod
            with zf_mod.ZipFile(bp, "r") as zf:
                bad = zf.testzip()
                if bad:
                    errors.append(f"Corrupt file in archive: {bad}")
                names = zf.namelist()
                if not any("chroma.sqlite3" in n for n in names):
                    errors.append("SQLite file missing from backup")
        else:
            sqlite_file = bp / "chroma.sqlite3"
            if not sqlite_file.exists():
                errors.append("chroma.sqlite3 missing from backup")
            else:
                conn = sqlite3_mod.connect(str(sqlite_file))
                check = conn.execute("PRAGMA integrity_check").fetchone()
                conn.close()
                if check[0] != "ok":
                    errors.append(f"SQLite integrity check failed: {check[0]}")
    except Exception as e:
        errors.append(f"Backup validation error: {e}")
    return errors


def backup_palace(
    palace_path: str,
    zip_mode: bool = False,
    max_backups: int = 5,
) -> BackupResult:
    """Create a timestamped binary backup of the palace directory.

    This is a fast restore path — copies the raw ChromaDB files so no
    re-embedding is needed. Use export_palace() instead for portability.

    Args:
        palace_path: Path to the palace directory.
        zip_mode: If True, create a zip archive instead of a directory copy.
        max_backups: Maximum number of backups to retain (0 = unlimited).

    Returns:
        BackupResult with backup path and size.
    """
    result = BackupResult()
    palace = Path(palace_path)

    if not palace.exists():
        result.errors.append(f"No palace found at {palace_path}")
        return result

    parent = palace.parent
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_name = f"palace-backup-{timestamp}"

    try:
        if zip_mode:
            backup_path = parent / f"{backup_name}.zip"
            with zipfile.ZipFile(backup_path, "w", zipfile.ZIP_DEFLATED) as zf:
                for root, _, files in os.walk(palace):
                    for f in files:
                        file_path = Path(root) / f
                        arcname = file_path.relative_to(palace)
                        zf.write(file_path, arcname)
            result.size_bytes = backup_path.stat().st_size
        else:
            backup_path = parent / backup_name
            shutil.copytree(palace, backup_path)
            result.size_bytes = sum(
                f.stat().st_size for f in backup_path.rglob("*") if f.is_file()
            )

        result.backup_path = str(backup_path)
        result.success = True
    except Exception as e:
        result.errors.append(f"Backup error: {e}")
        return result

    # Validate backup integrity
    validation_errors = _validate_backup(backup_path, zip_mode)
    if validation_errors:
        result.validation_errors = validation_errors
        logger.warning("Backup validation warnings: %s", validation_errors)

    # Prune old backups
    if max_backups > 0:
        try:
            pattern = "palace-backup-*.zip" if zip_mode else "palace-backup-*"
            existing = sorted(parent.glob(pattern))
            if not zip_mode:
                # Filter to directories only — prevents matching zip files without extension
                existing = [p for p in existing if p.is_dir()]
            if len(existing) > max_backups:
                to_remove = existing[: len(existing) - max_backups]
                for old in to_remove:
                    if old.is_dir():
                        shutil.rmtree(old)
                    else:
                        old.unlink()
                    result.pruned.append(str(old))
        except Exception as e:
            result.errors.append(f"Prune error: {e}")

    return result


# ── Format auto-detection dispatchers ────────────────────────────────


def auto_export(
    palace_path: str,
    output: str,
    kg: Optional[KnowledgeGraph] = None,
    format: str = "auto",
) -> ExportResult:
    """Export with auto-detected format based on output path.

    - output ends with .json → single-file format
    - output is a directory   → JSONL per wing/room

    Override with format="json" or format="jsonl".
    """
    if format == "json":
        return export_palace(palace_path, output, kg=kg)
    if format == "jsonl":
        return export_palace_jsonl(palace_path, output, kg=kg)

    # Auto-detect
    if output.endswith(".json"):
        return export_palace(palace_path, output, kg=kg)
    return export_palace_jsonl(palace_path, output, kg=kg)


def auto_import(
    input_path: str,
    palace_path: str,
    kg: Optional[KnowledgeGraph] = None,
) -> ImportResult:
    """Import with auto-detected format based on input path.

    - input ends with .json or is a file → single-file format
    - input is a directory                → JSONL per wing/room
    """
    if os.path.isfile(input_path):
        return import_palace(input_path, palace_path, kg=kg)
    if os.path.isdir(input_path):
        return import_palace_jsonl(input_path, palace_path, kg=kg)

    result = ImportResult()
    result.errors.append(f"Input path not found: {input_path}")
    return result
