"""
db.py — Database abstraction layer for MemPalace.

Provides a Collection-compatible interface that works with both
LanceDB (new default) and ChromaDB (legacy).

All callers use the same API regardless of backend:
    col.upsert(documents=[...], ids=[...], metadatas=[...])
    col.get(where={"wing": "x"}, limit=10, offset=0)
    col.query(query_texts=["search term"], n_results=5, where={"wing": "x"})
    col.delete(ids=["id1"])
    col.count()
"""

import json
import logging
import os
from typing import Optional

logger = logging.getLogger("mempalace")


# ── Where clause translation ─────────────────────────────────────────────────


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

    return " AND ".join(conditions) if conditions else None


# ── LanceDB backend ──────────────────────────────────────────────────────────


class LanceCollection:
    """LanceDB-backed collection with ChromaDB-compatible interface.

    Schema:
        id: string (primary key)
        document: string (verbatim text)
        vector: list<float32>[dim] (embedding)
        wing: string (indexed filter column)
        room: string (indexed filter column)
        source_file: string (indexed filter column)
        metadata_json: string (JSON of full metadata dict)
    """

    # Columns stored as real columns for filtering; everything else goes in metadata_json.
    FILTER_COLUMNS = {"wing", "room", "source_file", "node_id", "seq"}
    # Columns that are part of the schema but not user metadata.
    SCHEMA_COLUMNS = {
        "id", "document", "vector", "wing", "room", "source_file",
        "node_id", "seq", "metadata_json",
    }
    # Fields that are internal bookkeeping (not returned in metadata unless stored in metadata_json).
    INTERNAL_FIELDS = {"_distance", "_relevance_score"}

    def __init__(self, db, table_name: str, embedder):
        self._db = db
        self._table_name = table_name
        self._embedder = embedder
        self._table = None
        if table_name in self._list_table_names():
            self._table = db.open_table(table_name)
            self._check_dimension()

    def _list_table_names(self) -> list:
        """Get table names as a plain list (handles lancedb API variations)."""
        result = self._db.list_tables()
        if hasattr(result, "tables"):
            return result.tables  # ListTablesResponse object
        return list(result)  # plain list or iterable

    def _check_dimension(self):
        """Verify the embedder dimension matches the existing table's vector column."""
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
        """Convert to LanceDB record format, computing embeddings if needed."""
        if embeddings is None:
            embeddings = self._embedder.embed(documents)

        records = []
        for doc, id_, meta, vec in zip(documents, ids, metadatas, embeddings):
            # Inject the embedding model name so we can detect mismatches later
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
        """Create the table with initial data."""
        if self._table_name in self._list_table_names():
            self._table = self._db.open_table(self._table_name)
            self._table.add(records)
        else:
            self._table = self._db.create_table(self._table_name, data=records)

    def upsert(self, documents, ids, metadatas, embeddings=None):
        """Insert or update records. Computes embeddings automatically."""
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
            logger.debug("merge_insert failed (%s), falling back to delete+add", e)
            for r in records:
                escaped_id = r["id"].replace("'", "''")
                try:
                    self._table.delete(f"id = '{escaped_id}'")
                except Exception:
                    pass
            self._table.add(records)

    def add(self, documents, ids, metadatas, embeddings=None):
        """Add records. Uses upsert semantics (safe for duplicate IDs)."""
        self.upsert(documents, ids, metadatas, embeddings)

    def _refresh(self):
        """Refresh the table to see latest changes from other connections."""
        if self._table is not None:
            try:
                self._table.checkout_latest()
            except Exception:
                pass

    def get(self, ids=None, where=None, limit=None, offset=None, include=None):
        """Retrieve records by ID or metadata filter.

        Returns ChromaDB-compatible dict:
            {"ids": [...], "documents": [...], "metadatas": [...]}
        """
        if self._table is None:
            return {"ids": [], "documents": [], "metadatas": []}

        self._refresh()
        include = include or ["documents", "metadatas"]

        # Build filter
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
                # offset without limit — use a large limit
                query = query.limit(100_000).offset(offset)
            results = query.to_list()
        except Exception as e:
            logger.debug("get query failed: %s", e)
            return {"ids": [], "documents": [], "metadatas": []}

        return self._format_get_results(results, include)

    def query(self, query_texts, n_results=5, where=None, include=None):
        """Semantic vector search.

        Returns ChromaDB-compatible nested dict:
            {"ids": [[...]], "documents": [[...]], "metadatas": [[...]], "distances": [[...]]}
        """
        if self._table is None:
            return {"ids": [[]], "documents": [[]], "metadatas": [[]], "distances": [[]]}

        self._refresh()
        include = include or ["documents", "metadatas", "distances"]

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

    def delete(self, ids):
        """Delete records by ID.

        Performs a hard delete.
        """
        if self._table is None:
            return
        escaped = [id_.replace("'", "''") for id_ in ids]
        filter_str = "id IN ('" + "','".join(escaped) + "')"
        self._table.delete(filter_str)

    def count(self) -> int:
        """Count total records."""
        if self._table is None:
            return 0
        self._refresh()
        return self._table.count_rows()

    def _extract_metadata(self, record: dict) -> dict:
        """Extract metadata dict from a LanceDB record."""
        meta_json = record.get("metadata_json", "{}")
        try:
            return json.loads(meta_json)
        except (json.JSONDecodeError, TypeError):
            # Fallback: reconstruct from known columns
            return {
                k: v
                for k, v in record.items()
                if k not in self.SCHEMA_COLUMNS and not k.startswith("_")
            }

    def _format_get_results(self, results: list, include: list) -> dict:
        """Format LanceDB results into ChromaDB-compatible dict."""
        out = {"ids": []}
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


# ── ChromaDB backend (legacy) ────────────────────────────────────────────────


class ChromaCollection:
    """Thin wrapper around ChromaDB collection for API compatibility."""

    def __init__(self, collection):
        self._col = collection

    def upsert(self, documents, ids, metadatas, embeddings=None):
        kwargs = {"documents": documents, "ids": ids, "metadatas": metadatas}
        if embeddings is not None:
            kwargs["embeddings"] = embeddings
        return self._col.upsert(**kwargs)

    def add(self, documents, ids, metadatas, embeddings=None):
        kwargs = {"documents": documents, "ids": ids, "metadatas": metadatas}
        if embeddings is not None:
            kwargs["embeddings"] = embeddings
        return self._col.add(**kwargs)

    def get(self, ids=None, where=None, limit=None, offset=None, include=None):
        kwargs = {}
        if ids is not None:
            kwargs["ids"] = ids
        if where is not None:
            kwargs["where"] = where
        if limit is not None:
            kwargs["limit"] = limit
        if offset is not None:
            kwargs["offset"] = offset
        if include is not None:
            kwargs["include"] = include
        return self._col.get(**kwargs)

    def query(self, query_texts, n_results=5, where=None, include=None):
        kwargs = {"query_texts": query_texts, "n_results": n_results}
        if where:
            kwargs["where"] = where
        if include:
            kwargs["include"] = include
        return self._col.query(**kwargs)

    def delete(self, ids):
        return self._col.delete(ids=ids)

    def count(self):
        return self._col.count()


# ── Backend detection & factory ───────────────────────────────────────────────


def detect_backend(palace_path: str) -> str:
    """Auto-detect the storage backend for an existing palace.

    Returns "lance", "chroma", or "lance" (default for new palaces).
    """
    if not os.path.isdir(palace_path):
        return "lance"

    # LanceDB creates {table_name}.lance/ directories
    for entry in os.listdir(palace_path):
        if entry.endswith(".lance"):
            return "lance"

    # ChromaDB creates chroma.sqlite3
    if os.path.exists(os.path.join(palace_path, "chroma.sqlite3")):
        return "chroma"

    return "lance"


def open_collection(
    palace_path: str,
    collection_name: str = "mempalace_drawers",
    backend: str = None,
    embedder=None,
    create: bool = True,
):
    """Open or create a palace collection.

    Args:
        palace_path: Path to the palace data directory.
        collection_name: Table/collection name.
        backend: "lance" or "chroma". Auto-detected if None.
        embedder: Embedder instance (required for lance, ignored for chroma).
        create: If True, create the collection if it doesn't exist.

    Returns:
        A LanceCollection or ChromaCollection instance.
    """
    if backend is None:
        backend = detect_backend(palace_path)

    os.makedirs(palace_path, exist_ok=True)
    try:
        os.chmod(palace_path, 0o700)
    except (OSError, NotImplementedError):
        pass

    if backend == "lance":
        return _open_lance(palace_path, collection_name, embedder)
    elif backend == "chroma":
        return _open_chroma(palace_path, collection_name, create)
    else:
        raise ValueError(f"Unknown backend: {backend}")


def _open_lance(palace_path, collection_name, embedder):
    """Open a LanceDB-backed collection."""
    import lancedb

    if embedder is None:
        from .embeddings import get_embedder
        from .config import MempalaceConfig

        embedder = get_embedder(MempalaceConfig().embedder_config)

    db = lancedb.connect(palace_path)
    return LanceCollection(db, collection_name, embedder)


def _open_chroma(palace_path, collection_name, create):
    """Open a ChromaDB-backed collection."""
    import chromadb

    client = chromadb.PersistentClient(path=palace_path)
    try:
        col = client.get_collection(collection_name)
    except Exception:
        if create:
            col = client.create_collection(collection_name)
        else:
            raise
    return ChromaCollection(col)
