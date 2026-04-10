"""LanceDB-backed MemPalace collection adapter."""

import json
import logging
import os
from typing import Any, Dict, List, Optional

from .base import BaseCollection

logger = logging.getLogger("mempalace")


def _chroma_where_to_sql(where: dict) -> Optional[str]:
    """Convert ChromaDB-style where clause to SQL string for LanceDB.

    Supports:
        {"wing": "x"}                     → "wing = 'x'"
        {"$and": [{...}, {...}]}           → "(expr1) AND (expr2)"
        {"$or":  [{...}, {...}]}           → "(expr1) OR (expr2)"
        {"field": {"$gt": 5}}             → "field > 5"
    """
    if not where:
        return None

    if "$and" in where:
        parts = [_chroma_where_to_sql(clause) for clause in where["$and"]]
        parts = [p for p in parts if p]
        return " AND ".join(f"({p})" for p in parts) if parts else None

    if "$or" in where:
        parts = [_chroma_where_to_sql(clause) for clause in where["$or"]]
        parts = [p for p in parts if p]
        return " OR ".join(f"({p})" for p in parts) if parts else None

    conditions = []
    for key, value in where.items():
        if key.startswith("$"):
            continue
        if isinstance(value, str):
            escaped = value.replace("'", "''")
            conditions.append(f"{key} = '{escaped}'")
        elif isinstance(value, (int, float)):
            conditions.append(f"{key} = {value}")
        elif isinstance(value, dict):
            op_map = {
                "$gt": ">",
                "$gte": ">=",
                "$lt": "<",
                "$lte": "<=",
                "$ne": "!=",
                "$eq": "=",
            }
            for op, val in value.items():
                sql_op = op_map.get(op)
                if sql_op:
                    if isinstance(val, str):
                        escaped = val.replace("'", "''")
                        conditions.append(f"{key} {sql_op} '{escaped}'")
                    else:
                        conditions.append(f"{key} {sql_op} {val}")
                elif op == "$in" and isinstance(val, (list, tuple)):
                    escaped = [str(v).replace("'", "''") for v in val]
                    in_list = ", ".join(f"'{v}'" for v in escaped)
                    conditions.append(f"{key} IN ({in_list})")
                elif op == "$nin" and isinstance(val, (list, tuple)):
                    escaped = [str(v).replace("'", "''") for v in val]
                    in_list = ", ".join(f"'{v}'" for v in escaped)
                    conditions.append(f"{key} NOT IN ({in_list})")

    return " AND ".join(conditions) if conditions else None


class LanceCollection(BaseCollection):
    """LanceDB-backed collection with ChromaDB-compatible interface.

    Schema:
        id: string (primary key)
        document: string (verbatim text)
        vector: list<float32>[dim] (embedding)
        wing: string (indexed filter column)
        room: string (indexed filter column)
        source_file: string (indexed filter column)
        node_id: string (indexed filter column)
        seq: int (indexed filter column)
        metadata_json: string (JSON of full metadata dict)
    """

    FILTER_COLUMNS = {"wing", "room", "source_file", "node_id", "seq"}
    SCHEMA_COLUMNS = {
        "id", "document", "vector", "wing", "room", "source_file",
        "node_id", "seq", "metadata_json",
    }

    def __init__(self, db, table_name: str, embedder, sync_identity=None):
        self._db = db
        self._table_name = table_name
        self._embedder = embedder
        self._sync_identity = sync_identity
        self._table = None
        if table_name in self._list_table_names():
            self._table = db.open_table(table_name)
            self._check_dimension()

    def _list_table_names(self) -> list:
        result = self._db.list_tables()
        if hasattr(result, "tables"):
            return result.tables
        return list(result)

    def _check_dimension(self):
        import pyarrow as pa

        schema = self._table.schema
        vec_field = schema.field("vector")
        if not pa.types.is_fixed_size_list(vec_field.type):
            return
        stored_dim = vec_field.type.list_size
        expected_dim = self._embedder.dimension
        if stored_dim != expected_dim:
            raise RuntimeError(
                f"Embedder dimension mismatch: table '{self._table_name}' has "
                f"{stored_dim}d vectors but the active embedder "
                f"('{self._embedder.model_name}') produces {expected_dim}d. "
                f"Run 'mempalace reindex' to re-embed with the new model."
            )

    def _to_records(self, documents, ids, metadatas, embeddings=None):
        if embeddings is None:
            embeddings = self._embedder.embed(documents)

        records = []
        for doc, id_, meta, vec in zip(documents, ids, metadatas, embeddings):
            meta_with_model = dict(meta)
            meta_with_model.setdefault("embedding_model", self._embedder.model_name)
            record = {
                "id": id_,
                "document": doc,
                "vector": vec,
                "wing": str(meta.get("wing", "")),
                "room": str(meta.get("room", "")),
                "source_file": str(meta.get("source_file", "")),
                "node_id": str(meta.get("node_id", "")),
                "seq": int(meta.get("seq", 0)),
                "metadata_json": json.dumps(meta_with_model, default=str),
            }
            records.append(record)
        return records

    def _create_table(self, records):
        if self._table_name in self._list_table_names():
            self._table = self._db.open_table(self._table_name)
            self._table.add(records)
        else:
            self._table = self._db.create_table(self._table_name, data=records)

    def _inject_sync(self, metadatas: list) -> list:
        """Inject sync metadata (node_id, seq, updated_at) into a write batch."""
        if self._sync_identity is None:
            from ..sync_meta import get_identity

            self._sync_identity = get_identity()
        from ..sync_meta import inject_sync_meta

        return inject_sync_meta(metadatas, self._sync_identity)

    def add(self, *, documents, ids, metadatas=None, embeddings=None):
        self.upsert(documents=documents, ids=ids, metadatas=metadatas, embeddings=embeddings)

    def upsert(self, *, documents, ids, metadatas=None, embeddings=None, _raw=False):
        """Insert or update records. Computes embeddings automatically.

        Args:
            _raw: If True, skip sync metadata injection (used by sync apply).
        """
        metadatas = metadatas or [{} for _ in ids]
        if not _raw:
            metadatas = self._inject_sync(metadatas)
        records = self._to_records(documents, ids, metadatas, embeddings)

        if self._table is None:
            self._create_table(records)
            return

        try:
            (
                self._table.merge_insert("id")
                .when_matched_update_all()
                .when_not_matched_insert_all()
                .execute(records)
            )
        except Exception as e:
            logger.warning("merge_insert failed (%s), falling back to delete+add", e)
            for r in records:
                escaped_id = r["id"].replace("'", "''")
                try:
                    self._table.delete(f"id = '{escaped_id}'")
                except Exception:
                    pass
            self._table.add(records)

    def _refresh(self):
        if self._table is not None:
            try:
                self._table.checkout_latest()
            except Exception:
                pass

    def get(self, **kwargs: Any) -> Dict[str, Any]:
        if self._table is None:
            return {"ids": [], "documents": [], "metadatas": []}

        self._refresh()
        ids = kwargs.get("ids")
        where = kwargs.get("where")
        limit = kwargs.get("limit")
        offset = kwargs.get("offset")
        include = kwargs.get("include", ["documents", "metadatas"])

        if ids is not None:
            escaped = [id_.replace("'", "''") for id_ in ids]
            filter_str = "id IN ('" + "','".join(escaped) + "')"
        else:
            filter_str = _chroma_where_to_sql(where)

        try:
            query = self._table.search()
            if filter_str:
                query = query.where(filter_str)
            if limit is not None:
                if offset and offset > 0:
                    query = query.limit(limit).offset(offset)
                else:
                    query = query.limit(limit)
            elif offset and offset > 0:
                query = query.limit(100_000).offset(offset)
            results = query.to_list()
        except Exception as e:
            logger.debug("get query failed: %s", e)
            return {"ids": [], "documents": [], "metadatas": []}

        return self._format_get_results(results, include)

    def query(self, **kwargs: Any) -> Dict[str, Any]:
        if self._table is None:
            return {"ids": [[]], "documents": [[]], "metadatas": [[]], "distances": [[]]}

        self._refresh()
        query_texts = kwargs.get("query_texts", [])
        n_results = kwargs.get("n_results", 5)
        where = kwargs.get("where")
        include = kwargs.get("include", ["documents", "metadatas", "distances"])

        query_embedding = self._embedder.embed(query_texts[:1])[0]
        filter_str = _chroma_where_to_sql(where)

        try:
            search = self._table.search(query_embedding).metric("cosine").limit(n_results)
            if filter_str:
                search = search.where(filter_str)
            results = search.to_list()
        except Exception as e:
            logger.debug("query search failed: %s", e)
            return {"ids": [[]], "documents": [[]], "metadatas": [[]], "distances": [[]]}

        result_ids = []
        result_docs = []
        result_metas = []
        result_dists = []

        for r in results:
            result_ids.append(r.get("id", ""))
            result_docs.append(r.get("document", ""))
            result_dists.append(r.get("_distance", 0.0))
            result_metas.append(self._extract_metadata(r))

        return {
            "ids": [result_ids],
            "documents": [result_docs],
            "metadatas": [result_metas],
            "distances": [result_dists],
        }

    def delete(self, **kwargs: Any) -> None:
        """Delete records by ID.

        Performs a hard delete.  The sync layer (Phase 4) will convert
        these into tombstoned upserts when sync is active.
        """
        if self._table is None:
            return
        ids = kwargs.get("ids", [])
        escaped = [id_.replace("'", "''") for id_ in ids]
        filter_str = "id IN ('" + "','".join(escaped) + "')"
        self._table.delete(filter_str)

    def update(self, **kwargs: Any) -> None:
        """Update existing records by ID. Re-embeds if documents change."""
        ids = kwargs.get("ids", [])
        if not ids:
            return
        documents = kwargs.get("documents")
        metadatas = kwargs.get("metadatas")
        existing = self.get(ids=ids, include=["documents", "metadatas"])
        if not existing["ids"]:
            return
        docs = documents if documents is not None else existing.get("documents", [""] * len(ids))
        metas = metadatas if metadatas is not None else existing.get("metadatas", [{}] * len(ids))
        self.upsert(documents=docs, ids=ids, metadatas=metas)

    def count(self) -> int:
        if self._table is None:
            return 0
        self._refresh()
        return self._table.count_rows()

    def _extract_metadata(self, record: dict) -> dict:
        meta_json = record.get("metadata_json", "{}")
        try:
            return json.loads(meta_json)
        except (json.JSONDecodeError, TypeError):
            return {
                k: v
                for k, v in record.items()
                if k not in self.SCHEMA_COLUMNS and not k.startswith("_")
            }

    def _format_get_results(self, results: list, include: list) -> dict:
        out: Dict[str, List] = {"ids": []}
        if "documents" in include:
            out["documents"] = []
        if "metadatas" in include:
            out["metadatas"] = []

        for r in results:
            out["ids"].append(r.get("id", ""))
            if "documents" in include:
                out["documents"].append(r.get("document", ""))
            if "metadatas" in include:
                out["metadatas"].append(self._extract_metadata(r))

        return out


class LanceBackend:
    """Factory for the LanceDB backend."""

    def get_collection(
        self, palace_path: str, collection_name: str, create: bool = True,
        embedder=None, sync_identity=None,
    ):
        import lancedb

        if not create and not os.path.isdir(palace_path):
            raise FileNotFoundError(palace_path)

        if create:
            os.makedirs(palace_path, exist_ok=True)
            try:
                os.chmod(palace_path, 0o700)
            except (OSError, NotImplementedError):
                pass

        if embedder is None:
            from ..embeddings import get_embedder
            from ..config import MempalaceConfig

            embedder = get_embedder(MempalaceConfig().embedder_config)

        db = lancedb.connect(palace_path)
        return LanceCollection(db, collection_name, embedder, sync_identity=sync_identity)
