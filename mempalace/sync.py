"""
sync.py — Sync engine for multi-device MemPalace replication.

Hub-and-spoke model with version vectors.  Each node writes locally with
its own node_id + monotonic seq.  On sync, nodes exchange records the
other hasn't seen yet.

Changesets are lists of records with their full metadata (including
node_id, seq, updated_at).  The version vector is a dict mapping
node_id → highest_seq_seen_from_that_node.

Conflict resolution:
  - New records (id never seen): accepted unconditionally.
  - Same id on both sides: last-writer-wins by updated_at, node_id tiebreak.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field

from .sync_meta import NodeIdentity, get_identity

logger = logging.getLogger("mempalace.sync")


# ── Data types ────────────────────────────────────────────────────────────────


@dataclass
class SyncRecord:
    """One record in a changeset."""

    id: str
    document: str
    metadata: dict
    embedding: list[float] | None = None

    def to_dict(self) -> dict:
        d = {"id": self.id, "document": self.document, "metadata": self.metadata}
        if self.embedding is not None:
            d["embedding"] = self.embedding
        return d

    @classmethod
    def from_dict(cls, d: dict) -> SyncRecord:
        return cls(
            id=d["id"],
            document=d["document"],
            metadata=d["metadata"],
            embedding=d.get("embedding"),
        )


@dataclass
class ChangeSet:
    """A batch of records to sync."""

    source_node: str
    records: list[SyncRecord] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "source_node": self.source_node,
            "records": [r.to_dict() for r in self.records],
        }

    @classmethod
    def from_dict(cls, d: dict) -> ChangeSet:
        return cls(
            source_node=d["source_node"],
            records=[SyncRecord.from_dict(r) for r in d.get("records", [])],
        )


@dataclass
class MergeResult:
    """Result of applying a changeset."""

    accepted: int = 0
    rejected_conflicts: int = 0
    errors: list[str] = field(default_factory=list)


# ── Version vector ────────────────────────────────────────────────────────────


class VersionVector:
    """Maps node_id → highest seq seen from that node.

    Persisted as JSON in the palace directory.
    """

    def __init__(self, path: str = None):
        self._path = path
        self._vec: dict[str, int] = {}
        if path:
            self._load()

    def _load(self):
        if self._path:
            try:
                with open(self._path, "r") as f:
                    self._vec = json.load(f)
            except (FileNotFoundError, json.JSONDecodeError):
                self._vec = {}

    def _save(self):
        if self._path:
            with open(self._path, "w") as f:
                json.dump(self._vec, f)

    def save(self):
        """Persist current state to disk. Call after a batch of update() calls."""
        self._save()

    def get(self, node_id: str) -> int:
        return self._vec.get(node_id, 0)

    def update(self, node_id: str, seq: int):
        if seq > self._vec.get(node_id, 0):
            self._vec[node_id] = seq

    def update_from_records(self, records: list[SyncRecord]):
        """Advance the vector from a batch of records."""
        changed = False
        for r in records:
            nid = r.metadata.get("node_id", "")
            s = r.metadata.get("seq", 0)
            if isinstance(s, str):
                s = int(s)
            if nid and s > self._vec.get(nid, 0):
                self._vec[nid] = s
                changed = True
        if changed:
            self._save()

    def to_dict(self) -> dict[str, int]:
        return dict(self._vec)

    @classmethod
    def from_dict(cls, d: dict, path: str = None) -> VersionVector:
        vv = cls(path=None)  # don't load from file
        vv._path = path
        vv._vec = {k: int(v) for k, v in d.items()}
        return vv


# ── Sync engine ───────────────────────────────────────────────────────────────


class SyncEngine:
    """Extracts and applies changesets against a palace collection.

    Usage (push side — laptop sending to server):
        engine = SyncEngine(collection, identity, vv_path)
        changeset = engine.get_changes_since(remote_vv)
        # ... send changeset to server ...

    Usage (pull side — applying records from the other node):
        result = engine.apply_changes(changeset)
    """

    def __init__(self, collection, identity: NodeIdentity = None, vv_path: str = None):
        self._col = collection
        self._identity = identity or get_identity()
        self._vv = VersionVector(path=vv_path)

    @property
    def version_vector(self) -> dict[str, int]:
        return self._vv.to_dict()

    def _build_changes_filter(self, remote_vv: dict[str, int]) -> dict | None:
        """Build a where clause that selects records the remote hasn't seen.

        Uses indexed node_id/seq columns so LanceDB can filter at the
        storage layer instead of scanning every record into Python.
        """
        if not remote_vv:
            # Remote has seen nothing — return all records that have a seq
            return {"seq": {"$gt": 0}}

        # For each known node: records where seq > what remote has seen.
        # Plus: records from any node NOT in remote_vv (seq > 0).
        clauses = []
        for node_id, seen_seq in remote_vv.items():
            clauses.append({"$and": [{"node_id": node_id}, {"seq": {"$gt": seen_seq}}]})

        # Unknown nodes: build NOT-IN via chained $and of $ne
        unknown_filter = [{"seq": {"$gt": 0}}]
        for node_id in remote_vv:
            unknown_filter.append({"node_id": {"$ne": node_id}})
        clauses.append({"$and": unknown_filter})

        return {"$or": clauses}

    def get_changes_since(self, remote_vv: dict[str, int]) -> ChangeSet:
        """Get all records that the remote hasn't seen.

        Uses indexed node_id/seq columns for efficient filtering.
        Essential for hub-and-spoke: the hub relays records from any node.
        """
        our_node = self._identity.node_id
        where = self._build_changes_filter(remote_vv)

        records = self._col.get(
            where=where, limit=100_000, include=["documents", "metadatas"],
        )

        changeset = ChangeSet(source_node=our_node)
        for id_, doc, meta in zip(
            records["ids"], records["documents"], records["metadatas"]
        ):
            changeset.records.append(SyncRecord(id=id_, document=doc, metadata=meta))

        return changeset

    def apply_changes(self, changeset: ChangeSet) -> MergeResult:
        """Apply a changeset from a remote node.

        Conflict resolution: last-writer-wins by updated_at, then node_id.
        """
        result = MergeResult()

        if not changeset.records:
            return result

        # Batch-check which IDs already exist locally
        incoming_ids = [r.id for r in changeset.records]
        existing = self._col.get(ids=incoming_ids, include=["metadatas"])
        existing_map = {}
        for eid, emeta in zip(existing.get("ids", []), existing.get("metadatas", [])):
            existing_map[eid] = emeta

        to_upsert_docs = []
        to_upsert_ids = []
        to_upsert_metas = []
        to_upsert_embs = []

        for rec in changeset.records:
            local_meta = existing_map.get(rec.id)

            if local_meta is None:
                # New record — accept
                to_upsert_docs.append(rec.document)
                to_upsert_ids.append(rec.id)
                to_upsert_metas.append(rec.metadata)
                to_upsert_embs.append(rec.embedding)
                result.accepted += 1
            else:
                # Conflict — last-writer-wins
                if self._remote_wins(rec.metadata, local_meta):
                    to_upsert_docs.append(rec.document)
                    to_upsert_ids.append(rec.id)
                    to_upsert_metas.append(rec.metadata)
                    to_upsert_embs.append(rec.embedding)
                    result.accepted += 1
                else:
                    result.rejected_conflicts += 1

        if to_upsert_ids:
            # Split: records with embeddings vs those needing re-embedding
            with_emb_docs, with_emb_ids, with_emb_metas, with_emb_vecs = [], [], [], []
            without_emb_docs, without_emb_ids, without_emb_metas = [], [], []

            for doc, id_, meta, emb in zip(
                to_upsert_docs, to_upsert_ids, to_upsert_metas, to_upsert_embs
            ):
                if emb is not None:
                    with_emb_docs.append(doc)
                    with_emb_ids.append(id_)
                    with_emb_metas.append(meta)
                    with_emb_vecs.append(emb)
                else:
                    without_emb_docs.append(doc)
                    without_emb_ids.append(id_)
                    without_emb_metas.append(meta)

            if with_emb_ids:
                self._col.upsert(
                    documents=with_emb_docs,
                    ids=with_emb_ids,
                    metadatas=with_emb_metas,
                    embeddings=with_emb_vecs,
                    _raw=True,
                )
            if without_emb_ids:
                self._col.upsert(
                    documents=without_emb_docs,
                    ids=without_emb_ids,
                    metadatas=without_emb_metas,
                    _raw=True,
                )

        # Advance our version vector
        self._vv.update_from_records(changeset.records)

        return result

    @staticmethod
    def _parse_ts(raw: str):
        """Parse an ISO 8601 timestamp to a timezone-aware datetime."""
        from datetime import datetime, timezone

        if not raw:
            return datetime.min.replace(tzinfo=timezone.utc)
        # Handle 'Z' suffix
        normalized = raw.replace("Z", "+00:00")
        dt = datetime.fromisoformat(normalized)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt

    def _remote_wins(self, remote_meta: dict, local_meta: dict) -> bool:
        """Return True if the remote record should overwrite the local one.

        Comparison: updated_at descending (parsed as UTC), then node_id tiebreak.

        On exact timestamp tie the lexicographically higher node_id wins.
        This is arbitrary but deterministic — both sides reach the same
        conclusion without coordination.  Node IDs are stable across
        restarts (persisted in ~/.mempalace/node_id).
        """
        r_time = self._parse_ts(remote_meta.get("updated_at", ""))
        l_time = self._parse_ts(local_meta.get("updated_at", ""))

        if r_time > l_time:
            return True
        if r_time < l_time:
            return False

        # Tiebreak: higher node_id wins (deterministic)
        r_node = remote_meta.get("node_id", "")
        l_node = local_meta.get("node_id", "")
        return r_node > l_node
