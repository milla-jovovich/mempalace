"""
exporter.py — Export and import palace data for backup and migration.
=====================================================================

Exports all palace data (drawers from ChromaDB + knowledge graph from
SQLite) into a single portable JSON file. Imports from that file to
restore or migrate a palace to a new machine.

The export format is a self-describing JSON document:

    {
        "format": "mempalace_export",
        "version": 1,
        "exported_at": "2026-04-09T...",
        "drawers": [...],
        "kg_entities": [...],
        "kg_triples": [...]
    }

Zero API calls. Zero new dependencies. Uses only json + existing modules.

Usage:
    from mempalace.exporter import export_palace, import_palace

    export_palace(palace_path, output_file="palace_backup.json")
    import_palace("palace_backup.json", palace_path)

CLI:
    mempalace export palace_backup.json
    mempalace import palace_backup.json
"""

import json
import logging
import os
from datetime import datetime
from dataclasses import dataclass, field
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
