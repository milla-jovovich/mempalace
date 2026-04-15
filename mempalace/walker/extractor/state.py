"""Tracks which drawers have been extracted per extractor_version."""
from __future__ import annotations

from mempalace.knowledge_graph import KnowledgeGraph


class ExtractionState:
    """SQLite-backed extraction tracking. Shares knowledge_graph.db."""

    def __init__(self, kg: KnowledgeGraph) -> None:
        self._kg = kg
        self._init_table()

    def _init_table(self) -> None:
        with self._kg._write_lock:
            conn = self._kg._conn()
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS extraction_state (
                    drawer_id         TEXT PRIMARY KEY,
                    extractor_version TEXT NOT NULL,
                    extracted_at      TEXT DEFAULT CURRENT_TIMESTAMP,
                    triple_count      INTEGER DEFAULT 0,
                    entity_count      INTEGER DEFAULT 0
                )
                """
            )
            conn.commit()

    def is_extracted(self, drawer_id: str, version: str) -> bool:
        row = self._kg._conn().execute(
            "SELECT 1 FROM extraction_state WHERE drawer_id=? AND extractor_version=?",
            (drawer_id, version),
        ).fetchone()
        return row is not None

    def mark_extracted(
        self, drawer_id: str, version: str,
        triple_count: int, entity_count: int,
    ) -> None:
        with self._kg._write_lock:
            conn = self._kg._conn()
            conn.execute(
                """INSERT OR REPLACE INTO extraction_state
                   (drawer_id, extractor_version, extracted_at, triple_count, entity_count)
                   VALUES (?, ?, CURRENT_TIMESTAMP, ?, ?)""",
                (drawer_id, version, triple_count, entity_count),
            )
            conn.commit()

    def unextracted_ids(self, all_ids: list[str], version: str) -> list[str]:
        if not all_ids:
            return []
        conn = self._kg._conn()
        placeholders = ",".join("?" * len(all_ids))
        rows = conn.execute(
            f"""SELECT drawer_id FROM extraction_state
                WHERE extractor_version=? AND drawer_id IN ({placeholders})""",
            (version, *all_ids),
        ).fetchall()
        extracted = {r[0] for r in rows}
        return [i for i in all_ids if i not in extracted]

    def max_extracted_at(self, version: str) -> str | None:
        row = self._kg._conn().execute(
            "SELECT MAX(extracted_at) FROM extraction_state WHERE extractor_version=?",
            (version,),
        ).fetchone()
        return row[0] if row and row[0] else None
