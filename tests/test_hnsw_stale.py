"""
test_hnsw_stale.py — Regression tests for stale HNSW index detection.

When another process writes embeddings to chroma.sqlite3 while the MCP
server is running, the in-process HNSW index becomes stale and vector
queries fail with "Error finding id". mcp_server._get_client() detects
this by comparing the SQLite embedding count against a cached value,
and rebuilds the chromadb client on mismatch.

These tests exercise that detection path.
"""

import os

import chromadb


def _reset_hnsw_globals():
    """Reset the stale-index detection state between assertions."""
    from mempalace import mcp_server

    mcp_server._client_cache = None
    mcp_server._collection_cache = None
    mcp_server._last_known_count = 0


class TestSqliteEmbeddingCount:
    def test_returns_zero_when_db_missing(self, monkeypatch, config):
        from mempalace import mcp_server

        monkeypatch.setattr(mcp_server, "_config", config)
        _reset_hnsw_globals()

        # Fresh palace, no chroma.sqlite3 yet
        assert mcp_server._sqlite_embedding_count() == 0

    def test_returns_actual_count_after_add(self, monkeypatch, config, palace_path):
        from mempalace import mcp_server

        monkeypatch.setattr(mcp_server, "_config", config)
        _reset_hnsw_globals()

        client = chromadb.PersistentClient(path=palace_path)
        col = client.get_or_create_collection("mempalace_drawers")
        col.add(
            ids=["d1", "d2"],
            documents=["first drawer", "second drawer"],
            metadatas=[{"wing": "test"}, {"wing": "test"}],
        )
        del client

        assert mcp_server._sqlite_embedding_count() >= 2


class TestStaleIndexDetection:
    def test_rebuilds_when_external_process_adds_embeddings(
        self, monkeypatch, config, palace_path
    ):
        """Simulates `mempalace mine` writing to chroma while MCP holds a
        cached client. _get_client() should detect the count mismatch and
        build a fresh client."""
        from mempalace import mcp_server

        monkeypatch.setattr(mcp_server, "_config", config)
        _reset_hnsw_globals()

        # 1. Seed the palace with one drawer via a throwaway client so the
        #    sqlite file and embeddings table exist before we cache.
        seed_client = chromadb.PersistentClient(path=palace_path)
        seed_col = seed_client.get_or_create_collection("mempalace_drawers")
        seed_col.add(
            ids=["seed"],
            documents=["seed drawer"],
            metadatas=[{"wing": "test"}],
        )
        del seed_col
        del seed_client

        # 2. First _get_client() call caches a client + snapshots the count
        first_client = mcp_server._get_client()
        assert first_client is not None
        first_count = mcp_server._last_known_count
        assert first_count >= 1

        # 3. External process writes more embeddings to the same palace
        external = chromadb.PersistentClient(path=palace_path)
        ext_col = external.get_or_create_collection("mempalace_drawers")
        ext_col.add(
            ids=["external_1", "external_2"],
            documents=["ghost drawer one", "ghost drawer two"],
            metadatas=[{"wing": "test"}, {"wing": "test"}],
        )
        del ext_col
        del external

        # 4. Next _get_client() should notice the count mismatch and rebuild
        second_client = mcp_server._get_client()
        assert second_client is not first_client, (
            "client should have been rebuilt after external write"
        )
        assert mcp_server._last_known_count > first_count
        assert mcp_server._collection_cache is None, (
            "collection cache should be cleared on rebuild"
        )

    def test_no_rebuild_when_count_unchanged(self, monkeypatch, config, palace_path):
        from mempalace import mcp_server

        monkeypatch.setattr(mcp_server, "_config", config)
        _reset_hnsw_globals()

        seed = chromadb.PersistentClient(path=palace_path)
        col = seed.get_or_create_collection("mempalace_drawers")
        col.add(ids=["only"], documents=["only drawer"], metadatas=[{"wing": "t"}])
        del col
        del seed

        first_client = mcp_server._get_client()
        second_client = mcp_server._get_client()

        assert first_client is second_client, (
            "client should be cached when embedding count is stable"
        )

    def test_rebuild_skipped_on_first_call_even_if_db_exists(
        self, monkeypatch, config, palace_path
    ):
        """First _get_client() call should NOT rebuild, even though
        _last_known_count was 0 before — the initial call just snapshots."""
        from mempalace import mcp_server

        monkeypatch.setattr(mcp_server, "_config", config)
        _reset_hnsw_globals()

        seed = chromadb.PersistentClient(path=palace_path)
        col = seed.get_or_create_collection("mempalace_drawers")
        col.add(
            ids=["a", "b", "c"],
            documents=["one", "two", "three"],
            metadatas=[{"wing": "t"}] * 3,
        )
        del col
        del seed

        client = mcp_server._get_client()
        assert client is not None
        # After first call, we should have snapshotted the non-zero count
        assert mcp_server._last_known_count >= 3
