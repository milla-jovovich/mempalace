#!/usr/bin/env python3
"""
drawer_store.py — Minimal shared access to the primary drawer collection.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

import chromadb

from .config import DEFAULT_COLLECTION_NAME, MempalaceConfig

DRAWER_PAGE_SIZE = 1000
PROJECT_INGEST_MODE = "projects"
MANUAL_INGEST_MODE = "manual"
REFRESH_OWNER_KEY = "refresh_owner"


def _project_drawer_id(wing: str, room: str, source_file: str, chunk_index: int) -> str:
    digest = hashlib.sha256((source_file + str(chunk_index)).encode()).hexdigest()[:24]
    return f"drawer_{wing}_{room}_{digest}"


def _legacy_project_drawer_id(wing: str, room: str, source_file: str, chunk_index: int) -> str:
    digest = hashlib.md5(
        (source_file + str(chunk_index)).encode(), usedforsecurity=False
    ).hexdigest()[:16]
    return f"drawer_{wing}_{room}_{digest}"


def resolve_palace_path(
    palace_path: Optional[str] = None, config: Optional[MempalaceConfig] = None
) -> str:
    cfg = config or MempalaceConfig()
    raw_path = palace_path if palace_path is not None else cfg.palace_path
    return str(Path(raw_path).expanduser())


def resolve_collection_name(
    collection_name: Optional[str] = None,
    palace_path: Optional[str] = None,
    config: Optional[MempalaceConfig] = None,
) -> str:
    cfg = config or MempalaceConfig()
    if collection_name is not None:
        return collection_name
    if palace_path is not None:
        return DEFAULT_COLLECTION_NAME
    return cfg.collection_name


@dataclass(frozen=True)
class DrawerNamespace:
    """A source-backed drawer namespace that can be refreshed safely."""

    wing: str
    source_file: str
    ingest_mode: str

    @property
    def where(self) -> Dict[str, List[Dict[str, str]]]:
        return {"$and": [{"wing": self.wing}, {"source_file": self.source_file}]}

    @property
    def refresh_owner(self) -> str:
        return self.ingest_mode

    def matches(self, row: Dict[str, object]) -> bool:
        metadata = row["metadata"]
        if metadata.get("wing") != self.wing:
            return False
        if metadata.get("source_file") != self.source_file:
            return False

        refresh_owner = metadata.get(REFRESH_OWNER_KEY)
        if refresh_owner is not None:
            return (
                refresh_owner == self.refresh_owner
                and metadata.get("ingest_mode") == self.ingest_mode
            )

        return self._matches_legacy_row(row["id"], metadata)

    def _matches_legacy_row(self, row_id: str, metadata: Dict[str, object]) -> bool:
        if self.ingest_mode != PROJECT_INGEST_MODE:
            return False

        legacy_ingest_mode = metadata.get("ingest_mode")
        if legacy_ingest_mode not in (None, PROJECT_INGEST_MODE):
            return False

        room = metadata.get("room")
        chunk_index = metadata.get("chunk_index")
        if room is None or chunk_index is None:
            return False

        try:
            chunk_index = int(chunk_index)
        except (TypeError, ValueError):
            return False

        expected_id = _project_drawer_id(
            wing=self.wing,
            room=str(room),
            source_file=self.source_file,
            chunk_index=chunk_index,
        )
        legacy_id = _legacy_project_drawer_id(
            wing=self.wing,
            room=str(room),
            source_file=self.source_file,
            chunk_index=chunk_index,
        )
        return row_id in {expected_id, legacy_id}


class DrawerStore:
    """Thin wrapper around the configured Chroma drawer collection."""

    def __init__(
        self,
        palace_path: Optional[str] = None,
        collection_name: Optional[str] = None,
        config: Optional[MempalaceConfig] = None,
    ):
        self._config = config or MempalaceConfig()
        self.palace_path = resolve_palace_path(palace_path, self._config)
        self.collection_name = resolve_collection_name(collection_name, palace_path, self._config)

    def get_collection(self, create: bool = False):
        client = chromadb.PersistentClient(path=self.palace_path)
        if create:
            return client.get_or_create_collection(self.collection_name)
        return client.get_collection(self.collection_name)

    def get_rows(self, where: Optional[Dict] = None, include_documents: bool = False) -> List[Dict]:
        collection = self.get_collection()
        include = ["metadatas"]
        if include_documents:
            include.append("documents")

        rows = []
        offset = 0

        while True:
            kwargs = {
                "limit": DRAWER_PAGE_SIZE,
                "offset": offset,
                "include": include,
            }
            if where:
                kwargs["where"] = where

            results = collection.get(**kwargs)
            ids = results.get("ids", [])
            if not ids:
                break

            metadatas = results.get("metadatas", [])
            documents = results.get("documents", []) if include_documents else []

            for index, drawer_id in enumerate(ids):
                row = {
                    "id": drawer_id,
                    "metadata": metadatas[index] or {},
                }
                if include_documents:
                    row["document"] = documents[index]
                rows.append(row)

            if len(ids) < DRAWER_PAGE_SIZE:
                break
            offset += len(ids)

        return rows

    def get_namespace_rows(self, namespace: DrawerNamespace) -> List[Dict]:
        rows = self.get_rows(where=namespace.where, include_documents=False)
        return [row for row in rows if namespace.matches(row)]

    def upsert_rows(self, rows: List[Dict]) -> None:
        if not rows:
            return

        collection = self.get_collection(create=True)
        for start in range(0, len(rows), DRAWER_PAGE_SIZE):
            batch = rows[start : start + DRAWER_PAGE_SIZE]
            collection.upsert(
                ids=[row["id"] for row in batch],
                documents=[row["document"] for row in batch],
                metadatas=[row["metadata"] for row in batch],
            )

    def delete_ids(self, ids: List[str]) -> None:
        if not ids:
            return

        collection = self.get_collection(create=True)
        for start in range(0, len(ids), DRAWER_PAGE_SIZE):
            batch = ids[start : start + DRAWER_PAGE_SIZE]
            collection.delete(ids=batch)
