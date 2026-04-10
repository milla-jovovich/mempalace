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

    def get(self, node_id: str) -> int:
        return self._vec.get(node_id, 0)

    def update(self, node_id: str, seq: int):
        if seq > self._vec.get(node_id, 0):
            self._vec[node_id] = seq
            self._save()

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

    def get_changes_since(self, remote_vv: dict[str, int]) -> ChangeSet:
        """Get all local records that the remote hasn't seen.

        Scans records written by THIS node whose seq > remote_vv[our_node_id].
        """
        our_node = self._identity.node_id
        remote_knows = remote_vv.get(our_node, 0)

        # Scan all records and filter by node_id + seq
        # (LanceDB doesn't have complex metadata queries inside metadata_json,
        # so we scan and filter in Python.)
        all_records = self._col.get(limit=100_000, include=["documents", "metadatas"])

        changeset = ChangeSet(source_node=our_node)

        for id_, doc, meta in zip(
            all_records["ids"], all_records["documents"], all_records["metadatas"]
        ):
            rec_node = meta.get("node_id", "")
            rec_seq = meta.get("seq", 0)
            if isinstance(rec_seq, str):
                rec_seq = int(rec_seq)

            if rec_node == our_node and rec_seq > remote_knows:
                changeset.records.append(
                    SyncRecord(
                        id=id_,
                        document=doc,
                        metadata=meta,
                    )
                )

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
            # If any records lack embeddings, let the collection re-embed
            has_embs = all(e is not None for e in to_upsert_embs)
            self._col.upsert(
                documents=to_upsert_docs,
                ids=to_upsert_ids,
                metadatas=to_upsert_metas,
                embeddings=to_upsert_embs if has_embs else None,
                _raw=True,  # preserve original sync metadata
            )

        # Advance our version vector
        self._vv.update_from_records(changeset.records)

        return result

    def _remote_wins(self, remote_meta: dict, local_meta: dict) -> bool:
        """Return True if the remote record should overwrite the local one.

        Comparison: updated_at descending, then node_id descending as tiebreak.
        """
        r_time = remote_meta.get("updated_at", "")
        l_time = local_meta.get("updated_at", "")

        if r_time > l_time:
            return True
        if r_time < l_time:
            return False

        # Tiebreak: higher node_id wins (deterministic)
        r_node = remote_meta.get("node_id", "")
        l_node = local_meta.get("node_id", "")
        return r_node > l_node
