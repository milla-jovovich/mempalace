"""Elasticsearch storage backend using semantic_text + inference endpoints.

Uses Elastic inference endpoints for:
  - Embeddings: configured via inference_id (e.g. .jina-embeddings-v5-text-small)
  - Reranking: configured via rerank_id (e.g. .jina-reranker-v2)

The semantic_text field type handles embedding generation automatically at index
and query time. Reranking is applied via the text_similarity_reranker retriever.
"""

import logging

from .base import BaseCollection

logger = logging.getLogger("mempalace.elasticsearch")

_METADATA_KEYWORD_FIELDS = {
    "wing",
    "room",
    "source_file",
    "added_by",
    "hall",
    "topic",
    "type",
    "agent",
    "date",
    "ingest_mode",
    "extract_mode",
}

_METADATA_NUMERIC_FIELDS = {
    "chunk_index",
    "importance",
    "emotional_weight",
    "weight",
    "compression_ratio",
    "original_tokens",
}


def _es_config(config):
    """Extract elasticsearch settings from MempalaceConfig."""
    return config._file_config.get("elasticsearch", {})


def _build_index_name(prefix, collection_name):
    return f"{prefix}-{collection_name}"


def _where_to_es_filter(where):
    """Translate ChromaDB where-filter syntax to ES query DSL.

    Supports:
        {"field": "value"}            -> {"term": {"field": "value"}}
        {"$and": [{...}, {...}]}      -> {"bool": {"must": [...]}}
        {"$or": [{...}, {...}]}       -> {"bool": {"should": [...]}}
    """
    if not where:
        return None

    if "$and" in where:
        clauses = [_where_to_es_filter(clause) for clause in where["$and"]]
        return {"bool": {"must": [c for c in clauses if c]}}

    if "$or" in where:
        clauses = [_where_to_es_filter(clause) for clause in where["$or"]]
        return {"bool": {"should": [c for c in clauses if c], "minimum_should_match": 1}}

    terms = []
    for key, value in where.items():
        terms.append({"term": {key: value}})

    if len(terms) == 1:
        return terms[0]
    return {"bool": {"must": terms}}


def _hit_to_metadata(hit):
    """Extract flat metadata dict from an ES hit's _source."""
    source = hit["_source"]
    meta = {}
    for key, value in source.items():
        if key in ("content", "content_text"):
            continue
        if isinstance(value, (str, int, float, bool)) or value is None:
            meta[key] = value
    return meta


class ElasticsearchCollection(BaseCollection):
    """Elasticsearch collection using semantic_text for embeddings and reranker for search."""

    def __init__(self, name="mempalace_drawers", config=None, create=False):
        from ..config import MempalaceConfig

        config = config or MempalaceConfig()
        es_conf = _es_config(config)

        self._index_prefix = es_conf.get("index_prefix", "mempalace")
        self._index = _build_index_name(self._index_prefix, name)
        self._inference_id = es_conf.get("inference_id", ".jina-embeddings-v5-text-small")
        self._rerank_id = es_conf.get("rerank_id", ".jina-reranker-v2")

        try:
            from elasticsearch import Elasticsearch
        except ImportError:
            raise ImportError(
                "elasticsearch package required for ES backend. "
                "Install with: pip install 'mempalace[elasticsearch]'"
            )

        hosts = es_conf.get("hosts", ["http://localhost:9200"])
        api_key = es_conf.get("api_key")

        connect_kwargs = {"hosts": hosts, "request_timeout": 30}
        if api_key:
            connect_kwargs["api_key"] = api_key

        self._es = Elasticsearch(**connect_kwargs)
        self._ready = False

        if create:
            self._ensure_index()
        else:
            self._ready = self._es.indices.exists(index=self._index)

    def _ensure_index(self):
        """Create the index with semantic_text mapping if it doesn't exist."""
        if self._es.indices.exists(index=self._index):
            self._ready = True
            return

        mapping = {
            "mappings": {
                "properties": {
                    "content": {
                        "type": "semantic_text",
                        "inference_id": self._inference_id,
                    },
                    "content_text": {"type": "text"},
                    "wing": {"type": "keyword"},
                    "room": {"type": "keyword"},
                    "source_file": {"type": "keyword"},
                    "added_by": {"type": "keyword"},
                    "filed_at": {"type": "keyword"},
                    "hall": {"type": "keyword"},
                    "topic": {"type": "keyword"},
                    "type": {"type": "keyword"},
                    "agent": {"type": "keyword"},
                    "date": {"type": "keyword"},
                    "ingest_mode": {"type": "keyword"},
                    "extract_mode": {"type": "keyword"},
                    "chunk_index": {"type": "integer"},
                    "importance": {"type": "float"},
                    "emotional_weight": {"type": "float"},
                    "weight": {"type": "float"},
                    "compression_ratio": {"type": "float"},
                    "original_tokens": {"type": "integer"},
                }
            }
        }

        self._es.indices.create(index=self._index, body=mapping)
        self._ready = True
        logger.info(f"Created index {self._index} with inference_id={self._inference_id}")

    def add(self, ids, documents, metadatas=None):
        if not self._ready:
            self._ensure_index()

        ops = []
        for i, (doc_id, doc) in enumerate(zip(ids, documents)):
            body = {"content": doc, "content_text": doc}
            if metadatas and i < len(metadatas):
                for key, value in metadatas[i].items():
                    body[key] = value
            ops.append({"index": {"_index": self._index, "_id": doc_id}})
            ops.append(body)

        if ops:
            resp = self._es.bulk(operations=ops, refresh="wait_for")
            if resp.get("errors"):
                for item in resp["items"]:
                    action = item.get("index", item.get("create", {}))
                    if action.get("error"):
                        err = action["error"]
                        raise RuntimeError(
                            f"Bulk index error for {action.get('_id')}: "
                            f"{err.get('type')}: {err.get('reason')}"
                        )

    def get(self, ids=None, where=None, include=None, limit=None, offset=None):
        if not self._ready:
            return {"ids": [], "documents": [], "metadatas": []}

        if ids is not None:
            return self._get_by_ids(ids, include)

        return self._get_by_filter(where, include, limit, offset)

    def _get_by_ids(self, ids, include=None):
        try:
            resp = self._es.mget(index=self._index, ids=ids)
        except Exception:
            return {"ids": [], "documents": [], "metadatas": []}

        result_ids = []
        result_docs = []
        result_metas = []

        for doc in resp.get("docs", []):
            if not doc.get("found"):
                continue
            result_ids.append(doc["_id"])
            source = doc["_source"]
            if include is None or "documents" in include:
                result_docs.append(source.get("content_text", ""))
            if include is None or "metadatas" in include:
                result_metas.append(_hit_to_metadata(doc))

        result = {"ids": result_ids}
        if include is None or "documents" in include:
            result["documents"] = result_docs
        if include is None or "metadatas" in include:
            result["metadatas"] = result_metas
        return result

    def _get_by_filter(self, where, include=None, limit=None, offset=None):
        query_body = {"match_all": {}}
        es_filter = _where_to_es_filter(where)
        if es_filter:
            query_body = {"bool": {"must": [{"match_all": {}}, es_filter]}}

        search_kwargs = {
            "index": self._index,
            "query": query_body,
            "size": limit or 10000,
        }
        if offset:
            search_kwargs["from_"] = offset

        try:
            resp = self._es.search(**search_kwargs)
        except Exception:
            return {"ids": [], "documents": [], "metadatas": []}

        result_ids = []
        result_docs = []
        result_metas = []

        for hit in resp["hits"]["hits"]:
            result_ids.append(hit["_id"])
            source = hit["_source"]
            if include is None or "documents" in include:
                result_docs.append(source.get("content_text", ""))
            if include is None or "metadatas" in include:
                result_metas.append(_hit_to_metadata(hit))

        result = {"ids": result_ids}
        if include is None or "documents" in include:
            result["documents"] = result_docs
        if include is None or "metadatas" in include:
            result["metadatas"] = result_metas
        return result

    def query(self, query_texts, n_results=5, where=None, include=None):
        """Semantic search with optional reranking.

        First stage: semantic query against the content field (uses inference endpoint).
        Second stage: rerank top results via text_similarity_reranker.
        """
        if not self._ready:
            return {"ids": [[]], "documents": [[]], "metadatas": [[]], "distances": [[]]}

        text = query_texts[0] if query_texts else ""
        rank_window = max(n_results * 5, 25)

        inner_retriever = {
            "standard": {
                "query": self._build_semantic_query(text, where),
            }
        }

        retriever = {
            "text_similarity_reranker": {
                "retriever": inner_retriever,
                "field": "content_text",
                "inference_id": self._rerank_id,
                "inference_text": text,
                "rank_window_size": rank_window,
            }
        }

        try:
            resp = self._es.search(
                index=self._index,
                retriever=retriever,
                size=n_results,
            )
        except Exception as e:
            logger.warning(f"Reranker search failed, falling back to semantic-only: {e}")
            resp = self._search_semantic_only(text, where, n_results)

        return self._format_query_response(resp, include)

    def _build_semantic_query(self, text, where=None):
        semantic = {"semantic": {"field": "content", "query": text}}
        es_filter = _where_to_es_filter(where)
        if es_filter:
            return {"bool": {"must": [semantic], "filter": [es_filter]}}
        return semantic

    def _search_semantic_only(self, text, where, n_results):
        """Fallback when reranker is unavailable."""
        query = self._build_semantic_query(text, where)
        return self._es.search(index=self._index, query=query, size=n_results)

    def _format_query_response(self, resp, include=None):
        """Convert ES search response to ChromaDB-compatible query result format.

        Normalizes ES scores to a 0-1 distance range to match ChromaDB convention
        where callers compute similarity = 1 - distance.
        """
        all_ids = []
        all_docs = []
        all_metas = []
        all_dists = []

        hits = resp["hits"]["hits"]
        max_score = hits[0]["_score"] if hits else 1.0
        max_score = max(max_score, 1e-9)

        for hit in hits:
            all_ids.append(hit["_id"])
            source = hit["_source"]

            if include is None or "documents" in include:
                all_docs.append(source.get("content_text", ""))
            if include is None or "metadatas" in include:
                all_metas.append(_hit_to_metadata(hit))
            if include is None or "distances" in include:
                score = hit.get("_score", 0)
                similarity = min(score / max_score, 1.0)
                distance = 1.0 - similarity
                all_dists.append(round(distance, 6))

        result = {"ids": [all_ids]}
        if include is None or "documents" in include:
            result["documents"] = [all_docs]
        if include is None or "metadatas" in include:
            result["metadatas"] = [all_metas]
        if include is None or "distances" in include:
            result["distances"] = [all_dists]
        return result

    def delete(self, ids):
        if not self._ready:
            return
        ops = [{"delete": {"_index": self._index, "_id": doc_id}} for doc_id in ids]
        if ops:
            self._es.bulk(operations=ops, refresh="wait_for")

    def count(self):
        if not self._ready:
            return 0
        try:
            resp = self._es.count(index=self._index)
            return resp["count"]
        except Exception:
            return 0

    def upsert(self, ids, documents, metadatas=None):
        if not self._ready:
            self._ensure_index()

        ops = []
        for i, (doc_id, doc) in enumerate(zip(ids, documents)):
            body = {"content": doc, "content_text": doc}
            if metadatas and i < len(metadatas):
                for key, value in metadatas[i].items():
                    body[key] = value
            ops.append({"index": {"_index": self._index, "_id": doc_id}})
            ops.append(body)

        if ops:
            self._es.bulk(operations=ops, refresh="wait_for")
