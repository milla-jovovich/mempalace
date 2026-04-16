"""Milvus Lite-backed MemPalace collection adapter.

Uses the modern :class:`pymilvus.MilvusClient` API exclusively — no ORM,
no ``connections.connect``. The default URI is ``./milvus.db`` relative
to the palace path, so every palace is a single local file and no server
is required. Self-hosted Milvus can be used by passing an ``http://``
URI to :class:`MilvusBackend`.

Schema
------
Every MemPalace collection stores three fixed fields plus dynamic
metadata:

    id        VARCHAR(128)   primary key, MemPalace drawer IDs
    document  VARCHAR(65535) verbatim text content (no truncation)
    vector    FLOAT_VECTOR(384) MiniLM embedding in cosine space

``enable_dynamic_field=True`` means MemPalace metadata fields (``wing``,
``room``, ``hall``, ``source_file``, ``chunk_index``, …) are stored
alongside each record and can be filtered with the same ``where`` DSL
documented on :class:`~mempalace.backends.base.BaseCollection`.

Index
-----
``AUTOINDEX`` with ``metric_type="COSINE"``. This matches the Chroma
default (``hnsw:space=cosine``) so distances are directly comparable
across backends.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, Iterable, List, Optional, Tuple

from ..embeddings import DEFAULT_DIM, Embedder
from .base import (
    DEFAULT_GET_INCLUDE,
    DEFAULT_QUERY_INCLUDE,
    INCLUDE_DISTANCES,
    INCLUDE_DOCUMENTS,
    INCLUDE_METADATAS,
    BaseCollection,
    GetResult,
    QueryResult,
)

logger = logging.getLogger(__name__)


# --- constants --------------------------------------------------------------

DEFAULT_DB_FILENAME = "milvus.db"
DRAWER_ID_MAX_LENGTH = 128
DOCUMENT_MAX_LENGTH = 65535
# Milvus has a hard per-call ceiling on offset+limit for non-iterator
# reads. We page strictly below this; callers that need more use
# query_iterator transparently.
MILVUS_MAX_WINDOW = 16384
FIELD_ID = "id"
FIELD_DOCUMENT = "document"
FIELD_VECTOR = "vector"
RESERVED_FIELDS = {FIELD_ID, FIELD_DOCUMENT, FIELD_VECTOR, "distance"}


# --- where DSL translation --------------------------------------------------


def _quote_value(value: Any) -> str:
    """Serialize a Python value into a Milvus filter literal."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    if value is None:
        raise ValueError("null comparisons are not part of the portable where DSL")
    # Treat everything else as a string; escape backslashes and double quotes.
    text = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{text}"'


def _translate_clause(clause: Dict[str, Any]) -> str:
    if not isinstance(clause, dict):
        raise ValueError(f"where clause must be a dict, got {type(clause).__name__}")
    if not clause:
        return ""

    if len(clause) == 1:
        key, value = next(iter(clause.items()))
        if key == "$and":
            if not isinstance(value, list) or not value:
                raise ValueError("$and requires a non-empty list of clauses")
            parts = [_translate_clause(sub) for sub in value]
            return "(" + " and ".join(p for p in parts if p) + ")"
        if key == "$or":
            if not isinstance(value, list) or not value:
                raise ValueError("$or requires a non-empty list of clauses")
            parts = [_translate_clause(sub) for sub in value]
            return "(" + " or ".join(p for p in parts if p) + ")"
        if key.startswith("$"):
            raise ValueError(f"unsupported top-level operator: {key}")
        return _translate_field(key, value)

    # Multi-key dicts: Chroma treats these as implicit-$and but the
    # portable contract requires an explicit wrapper so the meaning is
    # obvious on both backends. Error loudly instead of guessing.
    raise ValueError(
        "where dict with multiple keys must be wrapped in explicit "
        f"$and (got keys: {sorted(clause.keys())})"
    )


def _translate_field(field: str, value: Any) -> str:
    if isinstance(value, dict):
        if set(value.keys()) != {"$in"}:
            raise ValueError(f"only $in is supported as a field operator (field={field!r})")
            # pragma: no cover
        items = value["$in"]
        if not isinstance(items, list) or not items:
            raise ValueError(f"$in requires a non-empty list (field={field!r})")
        rendered = ", ".join(_quote_value(v) for v in items)
        return f"{field} in [{rendered}]"
    return f"{field} == {_quote_value(value)}"


def translate_where(where: Optional[Dict[str, Any]]) -> str:
    """Public entry point. Returns a Milvus filter string or ``""``."""
    if not where:
        return ""
    return _translate_clause(where)


# --- collection -------------------------------------------------------------


class MilvusCollection(BaseCollection):
    """Adapter over a single Milvus collection within a palace."""

    def __init__(
        self,
        *,
        client,
        collection_name: str,
        embedder: Embedder,
        dim: int = DEFAULT_DIM,
    ):
        self._client = client
        self._name = collection_name
        self._embedder = embedder
        self._dim = dim

    # -- helpers ---------------------------------------------------------

    def _embed_many(self, texts: List[str]) -> List[List[float]]:
        return self._embedder.embed(texts)

    def _prepare_rows(
        self,
        *,
        ids: List[str],
        documents: List[str],
        metadatas: Optional[List[Dict[str, Any]]],
    ) -> List[Dict[str, Any]]:
        if metadatas is None:
            metadatas = [dict() for _ in ids]
        if not (len(ids) == len(documents) == len(metadatas)):
            raise ValueError(
                "ids, documents and metadatas must have equal length "
                f"(got {len(ids)}, {len(documents)}, {len(metadatas)})"
            )

        vectors = self._embed_many(list(documents))
        rows: List[Dict[str, Any]] = []
        for idx, (_id, doc, meta, vec) in enumerate(zip(ids, documents, metadatas, vectors)):
            if not isinstance(_id, str) or not _id:
                raise ValueError(f"row {idx}: id must be a non-empty string")
            if len(_id) > DRAWER_ID_MAX_LENGTH:
                raise ValueError(f"row {idx}: id length {len(_id)} exceeds {DRAWER_ID_MAX_LENGTH}")
            if not isinstance(doc, str):
                doc = "" if doc is None else str(doc)
            if len(doc) > DOCUMENT_MAX_LENGTH:
                # MemPalace's verbatim contract means we never silently
                # truncate. Surface a clear error so the caller can chunk.
                raise ValueError(
                    f"row {idx}: document length {len(doc)} exceeds "
                    f"Milvus VARCHAR limit {DOCUMENT_MAX_LENGTH} — chunk before storing"
                )
            row: Dict[str, Any] = {
                FIELD_ID: _id,
                FIELD_DOCUMENT: doc,
                FIELD_VECTOR: vec,
            }
            if meta:
                for k, v in meta.items():
                    if k in RESERVED_FIELDS:
                        raise ValueError(
                            f"row {idx}: metadata key {k!r} clashes with a reserved field"
                        )
                    row[k] = v
            rows.append(row)
        return rows

    def _output_fields_for_include(
        self, include: Iterable[str], *, with_distance: bool
    ) -> List[str]:
        wanted = set(include)
        fields: List[str] = [FIELD_ID]
        if INCLUDE_DOCUMENTS in wanted:
            fields.append(FIELD_DOCUMENT)
        if INCLUDE_METADATAS in wanted:
            # "*" pulls every dynamic field along with the scalar fields.
            fields.append("*")
        return fields

    def _extract_metadata(self, record: Dict[str, Any]) -> Dict[str, Any]:
        return {k: v for k, v in record.items() if k not in RESERVED_FIELDS}

    # -- writes ----------------------------------------------------------

    def add(
        self,
        *,
        ids: List[str],
        documents: List[str],
        metadatas: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        rows = self._prepare_rows(ids=ids, documents=documents, metadatas=metadatas)
        if not rows:
            return
        self._client.insert(collection_name=self._name, data=rows)

    def upsert(
        self,
        *,
        ids: List[str],
        documents: List[str],
        metadatas: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        rows = self._prepare_rows(ids=ids, documents=documents, metadatas=metadatas)
        if not rows:
            return
        self._client.upsert(collection_name=self._name, data=rows)

    def update(
        self,
        *,
        ids: List[str],
        documents: Optional[List[str]] = None,
        metadatas: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        if not ids:
            return
        # Milvus Lite can throw a segcore assertion when fetching by ID
        # from a freshly-created collection that has never been queried
        # or compacted. Treat any read failure here as "not found" so the
        # contract (update a missing ID -> KeyError) still holds.
        try:
            existing = (
                self._client.get(
                    collection_name=self._name,
                    ids=list(ids),
                    output_fields=["*"],
                )
                or []
            )
        except Exception:
            existing = []
        by_id = {rec[FIELD_ID]: rec for rec in existing}
        missing = [i for i in ids if i not in by_id]
        if missing:
            raise KeyError(f"update: ids not found: {missing}")

        new_docs = (
            list(documents) if documents is not None else [by_id[i][FIELD_DOCUMENT] for i in ids]
        )
        if metadatas is None:
            new_metas = [self._extract_metadata(by_id[i]) for i in ids]
        else:
            new_metas = [dict(m) for m in metadatas]

        self.upsert(ids=list(ids), documents=new_docs, metadatas=new_metas)

    def delete(
        self,
        *,
        ids: Optional[List[str]] = None,
        where: Optional[Dict[str, Any]] = None,
    ) -> None:
        if ids is None and where is None:
            raise ValueError("delete requires either ids= or where=")
        if ids is not None and len(ids) == 0:
            return
        kwargs: Dict[str, Any] = {"collection_name": self._name}
        if ids is not None:
            kwargs["ids"] = list(ids)
        if where is not None:
            kwargs["filter"] = translate_where(where)
        self._client.delete(**kwargs)

    # -- reads -----------------------------------------------------------

    def query(
        self,
        *,
        query_texts: List[str],
        n_results: int = 10,
        where: Optional[Dict[str, Any]] = None,
        include: Iterable[str] = DEFAULT_QUERY_INCLUDE,
    ) -> QueryResult:
        if not query_texts:
            return QueryResult()
        # MemPalace always queries with exactly one text; ignore extras
        # after computing the embedding (keeps parity with Chroma).
        vectors = self._embed_many(list(query_texts))
        include_set = set(include)
        output_fields = self._output_fields_for_include(
            include, with_distance=INCLUDE_DISTANCES in include_set
        )

        search_kwargs: Dict[str, Any] = {
            "collection_name": self._name,
            "data": vectors[:1],
            "limit": max(1, n_results),
            "output_fields": output_fields,
            "anns_field": FIELD_VECTOR,
            "search_params": {"metric_type": "COSINE"},
        }
        filter_expr = translate_where(where)
        if filter_expr:
            search_kwargs["filter"] = filter_expr

        raw = self._client.search(**search_kwargs)
        hits = raw[0] if raw else []

        ids: List[str] = []
        docs: List[str] = []
        metas: List[Dict[str, Any]] = []
        dists: List[float] = []
        for hit in hits:
            entity = hit.get("entity") if isinstance(hit, dict) else None
            if entity is None and isinstance(hit, dict):
                entity = hit
            ids.append(hit.get("id") if isinstance(hit, dict) else hit.id)
            if INCLUDE_DOCUMENTS in include_set:
                docs.append((entity or {}).get(FIELD_DOCUMENT, ""))
            if INCLUDE_METADATAS in include_set:
                metas.append(self._extract_metadata(entity or {}))
            if INCLUDE_DISTANCES in include_set:
                # Milvus COSINE returns a similarity-style score in [-1, 1]
                # where 1.0 means identical. Chroma's cosine "distance" is
                # 1 - similarity in [0, 2]. Convert so downstream rankers
                # (which expect lower = closer) keep working.
                score = (
                    hit.get("distance") if isinstance(hit, dict) else getattr(hit, "distance", 0.0)
                )
                dists.append(1.0 - float(score))
        return QueryResult(ids=ids, documents=docs, metadatas=metas, distances=dists)

    def get(
        self,
        *,
        ids: Optional[List[str]] = None,
        where: Optional[Dict[str, Any]] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
        include: Iterable[str] = DEFAULT_GET_INCLUDE,
    ) -> GetResult:
        include_list = list(include)
        output_fields = self._output_fields_for_include(include_list, with_distance=False)
        if ids is not None:
            if len(ids) == 0:
                return GetResult()
            records = (
                self._client.get(
                    collection_name=self._name,
                    ids=list(ids),
                    output_fields=output_fields,
                )
                or []
            )
        else:
            records = self._collect_by_filter(
                filter_expr=translate_where(where),
                output_fields=output_fields,
                limit=limit,
                offset=offset or 0,
            )

        result_ids: List[str] = []
        result_docs: List[str] = []
        result_metas: List[Dict[str, Any]] = []
        include_set = set(include_list)
        for rec in records:
            result_ids.append(rec.get(FIELD_ID, ""))
            if INCLUDE_DOCUMENTS in include_set:
                result_docs.append(rec.get(FIELD_DOCUMENT, ""))
            if INCLUDE_METADATAS in include_set:
                result_metas.append(self._extract_metadata(rec))
        return GetResult(ids=result_ids, documents=result_docs, metadatas=result_metas)

    def _collect_by_filter(
        self,
        *,
        filter_expr: str,
        output_fields: List[str],
        limit: Optional[int],
        offset: int,
    ) -> List[Dict[str, Any]]:
        # Milvus's id primary key is a VARCHAR — there's no natural numeric
        # filter that matches "every row". Passing filter="" works with
        # modern MilvusClient.query / MilvusClient.query_iterator.
        filter_str = filter_expr or ""

        # If the caller's window fits below Milvus's hard ceiling, use a
        # single query. Otherwise fall through to the iterator.
        effective_limit = limit if limit is not None else None
        if effective_limit is not None and offset + effective_limit <= MILVUS_MAX_WINDOW:
            kwargs: Dict[str, Any] = {
                "collection_name": self._name,
                "output_fields": output_fields,
                "limit": effective_limit,
            }
            if filter_str:
                kwargs["filter"] = filter_str
            if offset:
                kwargs["offset"] = offset
            return list(self._client.query(**kwargs) or [])

        # Paginate via query_iterator. This is the path exercised by
        # full-scan callers (exporter, migrate, _fetch_all_metadata).
        iterator_kwargs: Dict[str, Any] = {
            "collection_name": self._name,
            "output_fields": output_fields,
            "batch_size": min(MILVUS_MAX_WINDOW, effective_limit or 1000),
        }
        if filter_str:
            iterator_kwargs["filter"] = filter_str
        iterator = self._client.query_iterator(**iterator_kwargs)

        skipped = 0
        collected: List[Dict[str, Any]] = []
        try:
            while True:
                batch = iterator.next()
                if not batch:
                    break
                for rec in batch:
                    if skipped < offset:
                        skipped += 1
                        continue
                    collected.append(rec)
                    if effective_limit is not None and len(collected) >= effective_limit:
                        return collected
        finally:
            try:
                iterator.close()
            except Exception:
                pass
        return collected

    def count(self) -> int:
        rows = (
            self._client.query(
                collection_name=self._name,
                filter="",
                output_fields=["count(*)"],
            )
            or []
        )
        if not rows:
            return 0
        # Milvus returns [{"count(*)": N}].
        first = rows[0]
        return int(first.get("count(*)", first.get("count", 0)))


# --- backend ---------------------------------------------------------------


class MilvusBackend:
    """Factory for the Milvus Lite (or self-hosted Milvus) backend."""

    def __init__(
        self,
        *,
        uri: Optional[str] = None,
        db_filename: str = DEFAULT_DB_FILENAME,
        embedder: Optional[Embedder] = None,
    ):
        """Create a new backend.

        Parameters
        ----------
        uri:
            Optional explicit connection URI. When ``None`` (the default),
            every palace gets its own ``./milvus.db`` file under
            ``palace_path/``. Pass ``http://host:19530`` to point at a
            self-hosted Milvus server instead.
        db_filename:
            File name used for the per-palace Milvus Lite database. Only
            honored when ``uri`` is ``None``.
        embedder:
            Inject a pre-configured embedder (useful for tests that want
            to pin a ``local_dir``). A shared default is used otherwise.
        """
        self._uri_override = uri
        self._db_filename = db_filename
        self._embedder = embedder
        # (palace_path_or_uri_key) -> MilvusClient
        self._clients: dict = {}

    # -- connection ------------------------------------------------------

    def _get_embedder(self) -> Embedder:
        if self._embedder is not None:
            return self._embedder
        from ..embeddings import get_default_embedder

        self._embedder = get_default_embedder()
        return self._embedder

    def _resolve_uri(self, palace_path: str) -> str:
        if self._uri_override:
            return self._uri_override
        return os.path.join(palace_path, self._db_filename)

    def _client(self, palace_path: str):
        from pymilvus import MilvusClient  # deferred

        uri = self._resolve_uri(palace_path)
        if uri not in self._clients:
            self._clients[uri] = MilvusClient(uri=uri)
        return self._clients[uri]

    # -- lifecycle -------------------------------------------------------

    @staticmethod
    def backend_version() -> str:
        import pymilvus  # deferred

        return pymilvus.__version__

    def get_collection(
        self,
        palace_path: str,
        collection_name: str,
        create: bool = False,
    ) -> MilvusCollection:
        """Return a :class:`MilvusCollection` bound to ``palace_path``."""
        uri = self._resolve_uri(palace_path)
        is_local_file = not (uri.startswith("http://") or uri.startswith("https://"))

        if is_local_file:
            parent = os.path.dirname(uri) or "."
            if not create and not os.path.isdir(parent):
                raise FileNotFoundError(palace_path)
            if create:
                os.makedirs(parent, exist_ok=True)
                try:
                    os.chmod(parent, 0o700)
                except (OSError, NotImplementedError):
                    pass

        client = self._client(palace_path)
        if not client.has_collection(collection_name):
            if not create:
                raise FileNotFoundError(f"collection {collection_name!r} does not exist at {uri}")
            self._create_collection(client, collection_name)

        return MilvusCollection(
            client=client,
            collection_name=collection_name,
            embedder=self._get_embedder(),
        )

    def get_or_create_collection(self, palace_path: str, collection_name: str) -> MilvusCollection:
        return self.get_collection(palace_path, collection_name, create=True)

    def create_collection(
        self,
        palace_path: str,
        collection_name: str,
        hnsw_space: str = "cosine",
    ) -> MilvusCollection:
        """Create (not get-or-create). ``hnsw_space`` is accepted for parity
        with :class:`~mempalace.backends.chroma.ChromaBackend` but must be
        ``cosine`` since Milvus AUTOINDEX + COSINE is what we standardize on.
        """
        if hnsw_space.lower() != "cosine":
            raise ValueError(f"MilvusBackend only supports cosine metric (got {hnsw_space!r})")
        uri = self._resolve_uri(palace_path)
        if not (uri.startswith("http://") or uri.startswith("https://")):
            parent = os.path.dirname(uri) or "."
            os.makedirs(parent, exist_ok=True)
        client = self._client(palace_path)
        if client.has_collection(collection_name):
            raise ValueError(f"collection {collection_name!r} already exists")
        self._create_collection(client, collection_name)
        return MilvusCollection(
            client=client,
            collection_name=collection_name,
            embedder=self._get_embedder(),
        )

    def delete_collection(self, palace_path: str, collection_name: str) -> None:
        client = self._client(palace_path)
        if client.has_collection(collection_name):
            client.drop_collection(collection_name)

    # -- schema ----------------------------------------------------------

    def _create_collection(self, client, collection_name: str) -> None:
        from pymilvus import DataType  # deferred

        schema = client.create_schema(
            auto_id=False,
            enable_dynamic_field=True,
            description="MemPalace drawers — verbatim text + MiniLM vectors",
        )
        schema.add_field(
            field_name=FIELD_ID,
            datatype=DataType.VARCHAR,
            is_primary=True,
            max_length=DRAWER_ID_MAX_LENGTH,
        )
        schema.add_field(
            field_name=FIELD_DOCUMENT,
            datatype=DataType.VARCHAR,
            max_length=DOCUMENT_MAX_LENGTH,
        )
        schema.add_field(
            field_name=FIELD_VECTOR,
            datatype=DataType.FLOAT_VECTOR,
            dim=self._get_embedder().dim,
        )

        index_params = client.prepare_index_params()
        index_params.add_index(
            field_name=FIELD_VECTOR,
            index_type="AUTOINDEX",
            metric_type="COSINE",
        )

        client.create_collection(
            collection_name=collection_name,
            schema=schema,
            index_params=index_params,
        )


# --- module-level helper for where-DSL sanity tests ------------------------


def compile_where(where: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
    """Return (milvus_filter, original_where) — useful for debugging tools."""
    return translate_where(where), where
