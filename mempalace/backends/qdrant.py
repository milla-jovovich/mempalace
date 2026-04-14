"""Qdrant-backed MemPalace collection adapter."""

import logging
import os
import uuid
from typing import Any, Dict, List, Optional

from .base import BaseCollection

logger = logging.getLogger(__name__)

NAMESPACE_MEMPALACE = uuid.UUID("12345678-1234-5678-1234-567812345678")
EMBEDDING_DIM = 384
PAYLOAD_INDEXED_FIELDS = [
    "wing",
    "room",
    "source_file",
    "mined_at",
    "thread_id",
    "aaak_type",
]


def _lazy_import_qdrant():
    """Lazy import of qdrant_client to avoid heavy dependency at module load."""
    try:
        from qdrant_client import QdrantClient
        from qdrant_client.models import (
            Distance,
            FieldCondition,
            Filter,
            MatchAny,
            MatchExcept,
            MatchText,
            MatchValue,
            PayloadSchemaType,
            PointStruct,
            VectorParams,
        )

        return (
            QdrantClient,
            Distance,
            FieldCondition,
            Filter,
            MatchAny,
            MatchExcept,
            MatchText,
            MatchValue,
            PayloadSchemaType,
            PointStruct,
            VectorParams,
        )
    except ImportError as e:
        raise ImportError(
            "Qdrant backend requires qdrant-client. "
            "Install with: pip install mempalace[qdrant]"
        ) from e


def _lazy_import_embedder():
    """Lazy import of sentence-transformers to avoid heavy dependency at module load."""
    try:
        from sentence_transformers import SentenceTransformer

        return SentenceTransformer
    except ImportError as e:
        raise ImportError(
            "Qdrant backend requires sentence-transformers. "
            "Install with: pip install mempalace[qdrant]"
        ) from e


_embedder_model = None


def _get_embedder():
    """Get or create the sentence-transformers model (lazy singleton)."""
    global _embedder_model
    if _embedder_model is None:
        SentenceTransformer = _lazy_import_embedder()
        _embedder_model = SentenceTransformer("all-MiniLM-L6-v2", device="cpu")
    return _embedder_model


def _to_qdrant_id(chroma_id: str) -> str:
    """Deterministic UUID5 from ChromaDB string ID."""
    return str(uuid.uuid5(NAMESPACE_MEMPALACE, chroma_id))


def _condition_from_clause(clause: dict):
    """Convert a single {field: value_or_operator} clause to a Qdrant condition."""
    (
        _,
        _,
        FieldCondition,
        Filter,
        MatchAny,
        MatchExcept,
        MatchText,
        MatchValue,
        _,
        _,
        _,
    ) = _lazy_import_qdrant()

    if len(clause) != 1:
        return _build_filter(clause)
    key, value = next(iter(clause.items()))

    if key == "$and":
        return Filter(must=[_condition_from_clause(c) for c in value])
    if key == "$or":
        return Filter(should=[_condition_from_clause(c) for c in value])

    if isinstance(value, dict):
        op, operand = next(iter(value.items()))
        if op == "$eq":
            return FieldCondition(key=key, match=MatchValue(value=operand))
        if op == "$ne":
            return Filter(must_not=[FieldCondition(key=key, match=MatchValue(value=operand))])
        if op == "$in":
            return FieldCondition(key=key, match=MatchAny(any=operand))
        if op == "$nin":
            return FieldCondition(key=key, match=MatchExcept(**{"except": operand}))
        if op == "$contains":
            return FieldCondition(key=key, match=MatchText(text=operand))
        raise NotImplementedError(f"Operator {op} not supported")

    # Implicit $eq
    return FieldCondition(key=key, match=MatchValue(value=value))


def _build_filter(where: Optional[dict]):
    """Translate ChromaDB where clause to Qdrant Filter.

    Supports: $eq, $ne, $in, $nin, $and, $or, $contains
    Short form: {"wing": "todo"} == {"wing": {"$eq": "todo"}}
    """
    (_, _, _, Filter, _, _, _, _, _, _, _) = _lazy_import_qdrant()

    if not where:
        return None

    if "$and" in where and len(where) == 1:
        return Filter(must=[_condition_from_clause(c) for c in where["$and"]])
    if "$or" in where and len(where) == 1:
        return Filter(should=[_condition_from_clause(c) for c in where["$or"]])

    # Implicit AND across multiple fields
    return Filter(must=[_condition_from_clause({k: v}) for k, v in where.items()])


class QdrantCollection(BaseCollection):
    """ChromaDB-compatible Collection wrapper over Qdrant."""

    def __init__(self, client, name: str):
        """Initialize Qdrant collection wrapper.

        Args:
            client: QdrantClient instance
            name: Collection name
        """
        self._client = client
        self._name = name

    def add(
        self,
        *,
        documents: List[str],
        ids: List[str],
        metadatas: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        """Add documents to the collection."""
        (_, _, _, _, _, _, _, _, _, PointStruct, _) = _lazy_import_qdrant()

        if metadatas is None:
            metadatas = [{}] * len(documents)

        embedder = _get_embedder()
        embeddings = embedder.encode(documents, show_progress_bar=False, batch_size=32).tolist()

        points = [
            PointStruct(
                id=_to_qdrant_id(cid),
                vector=emb,
                payload={**meta, "document": doc, "_original_id": cid},
            )
            for cid, doc, meta, emb in zip(ids, documents, metadatas, embeddings)
        ]
        self._client.upsert(collection_name=self._name, points=points)

    def upsert(
        self,
        *,
        documents: List[str],
        ids: List[str],
        metadatas: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        """Upsert documents (same as add for Qdrant)."""
        self.add(documents=documents, ids=ids, metadatas=metadatas)

    def query(self, **kwargs: Any) -> Dict[str, Any]:
        """Query by text or pre-computed vectors.

        Args:
            query_texts: List of query strings (will be embedded)
            query_embeddings: Pre-computed query vectors
            n_results: Number of results per query (default 10)
            where: ChromaDB-style filter dict
            include: List of fields to include (default ["documents", "metadatas"])

        Returns:
            Dict with keys: ids, documents, metadatas, distances (nested lists)
        """
        query_texts = kwargs.get("query_texts")
        query_embeddings = kwargs.get("query_embeddings")
        n_results = kwargs.get("n_results", 10)
        where = kwargs.get("where")
        include = kwargs.get("include", ["documents", "metadatas"])

        if query_embeddings is not None:
            query_vectors = query_embeddings
        elif query_texts is not None:
            embedder = _get_embedder()
            query_vectors = embedder.encode(query_texts, show_progress_bar=False).tolist()
        else:
            raise ValueError("query_texts or query_embeddings required")

        qfilter = _build_filter(where)
        results = {"ids": [], "documents": [], "metadatas": [], "distances": []}

        for qv in query_vectors:
            response = self._client.query_points(
                collection_name=self._name,
                query=qv,
                query_filter=qfilter,
                limit=n_results,
                with_payload=True,
            )
            hits = response.points
            results["ids"].append([h.payload.get("_original_id", str(h.id)) for h in hits])
            if "documents" in include:
                results["documents"].append([h.payload.get("document", "") for h in hits])
            if "metadatas" in include:
                results["metadatas"].append(
                    [
                        {k: v for k, v in h.payload.items() if k not in ("document", "_original_id")}
                        for h in hits
                    ]
                )
            # Qdrant cosine is in [-1, 1]. Normalize to ChromaDB distance [0, 1]
            results["distances"].append([max(0.0, 1.0 - h.score) for h in hits])
        return results

    def get(self, **kwargs: Any) -> Dict[str, Any]:
        """Retrieve documents by ID or filter.

        Args:
            ids: List of document IDs to retrieve
            where: ChromaDB-style filter dict
            limit: Maximum number of results
            offset: Offset for pagination (default 0)
            include: List of fields to include (default ["documents", "metadatas"])

        Returns:
            Dict with keys: ids, documents, metadatas, embeddings (if requested)
        """
        ids = kwargs.get("ids")
        where = kwargs.get("where")
        limit = kwargs.get("limit")
        offset = kwargs.get("offset", 0)
        include = kwargs.get("include", ["documents", "metadatas"])

        want_vectors = "embeddings" in include
        qfilter = _build_filter(where)

        if ids:
            qids = [_to_qdrant_id(cid) for cid in ids]
            points = self._client.retrieve(
                collection_name=self._name,
                ids=qids,
                with_payload=True,
                with_vectors=want_vectors,
            )
        else:
            # Qdrant scroll: offset is opaque token (not int)
            points, _ = self._client.scroll(
                collection_name=self._name,
                scroll_filter=qfilter,
                limit=limit or 10000,
                offset=offset if offset else None,
                with_payload=True,
                with_vectors=want_vectors,
            )

        result = {"ids": [p.payload.get("_original_id", str(p.id)) for p in points]}
        if "documents" in include:
            result["documents"] = [p.payload.get("document", "") for p in points]
        if "metadatas" in include:
            result["metadatas"] = [
                {k: v for k, v in p.payload.items() if k not in ("document", "_original_id")}
                for p in points
            ]
        if want_vectors:
            result["embeddings"] = [p.vector for p in points]
        return result

    def delete(self, **kwargs: Any) -> None:
        """Delete documents by ID or filter.

        Args:
            ids: List of document IDs to delete
            where: ChromaDB-style filter dict
        """
        ids = kwargs.get("ids")
        where = kwargs.get("where")

        if ids:
            qids = [_to_qdrant_id(cid) for cid in ids]
            self._client.delete(collection_name=self._name, points_selector=qids)
        elif where:
            qfilter = _build_filter(where)
            self._client.delete(collection_name=self._name, points_selector=qfilter)

    def count(self) -> int:
        """Return the number of documents in the collection."""
        return self._client.count(collection_name=self._name).count


class QdrantBackend:
    """Factory for MemPalace's Qdrant backend."""

    def get_collection(
        self, palace_path: str, collection_name: str, create: bool = False
    ) -> QdrantCollection:
        """Get or create a Qdrant collection.

        Args:
            palace_path: Path to the Qdrant storage directory
            collection_name: Name of the collection
            create: If True, create collection and directory if missing

        Returns:
            QdrantCollection instance

        Raises:
            FileNotFoundError: If palace_path doesn't exist and create=False
            ValueError: If collection doesn't exist and create=False
        """
        (
            QdrantClient,
            Distance,
            _,
            _,
            _,
            _,
            _,
            _,
            PayloadSchemaType,
            _,
            VectorParams,
        ) = _lazy_import_qdrant()

        if not create and not os.path.isdir(palace_path):
            raise FileNotFoundError(palace_path)

        if create:
            os.makedirs(palace_path, exist_ok=True)
            try:
                os.chmod(palace_path, 0o700)
            except (OSError, NotImplementedError):
                pass

        client = QdrantClient(path=palace_path)

        # Check if collection exists
        collections = [c.name for c in client.get_collections().collections]

        if collection_name in collections:
            # Verify schema
            info = client.get_collection(collection_name=collection_name)
            vec_cfg = info.config.params.vectors
            if hasattr(vec_cfg, "size") and vec_cfg.size != EMBEDDING_DIM:
                raise ValueError(
                    f"Collection '{collection_name}' has dimension {vec_cfg.size}, "
                    f"expected {EMBEDDING_DIM}"
                )
            return QdrantCollection(client, collection_name)

        if not create:
            raise ValueError(f"Collection '{collection_name}' does not exist")

        # Create collection
        client.create_collection(
            collection_name=collection_name,
            vectors_config=VectorParams(size=EMBEDDING_DIM, distance=Distance.COSINE),
        )

        # Create payload indexes for fast filtering
        for field in PAYLOAD_INDEXED_FIELDS:
            try:
                client.create_payload_index(
                    collection_name=collection_name,
                    field_name=field,
                    field_schema=PayloadSchemaType.KEYWORD,
                )
            except Exception:
                logger.debug(f"Could not create index for field {field}")

        return QdrantCollection(client, collection_name)
