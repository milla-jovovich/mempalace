"""Tests for the Milvus Lite storage backend.

Split into two tiers:

* pure-Python tests for the ``where``-DSL translator that do not need a
  running Milvus (run everywhere, every time)
* end-to-end tests that spin up Milvus Lite in a ``tmp_path`` and drive
  the full adapter (skipped gracefully when ``pymilvus``/``milvus-lite``
  or the ONNX model aren't available)
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest


# ── where-DSL translation (pure, no backend deps) ────────────────────────


pymilvus = pytest.importorskip("pymilvus", reason="pymilvus not installed")


from mempalace.backends.milvus import translate_where  # noqa: E402


class TestTranslateWhere:
    def test_empty_returns_empty_string(self):
        assert translate_where(None) == ""
        assert translate_where({}) == ""

    def test_simple_equality(self):
        assert translate_where({"wing": "project"}) == 'wing == "project"'

    def test_integer_equality(self):
        assert translate_where({"chunk_index": 5}) == "chunk_index == 5"

    def test_boolean_equality(self):
        assert translate_where({"is_archived": True}) == "is_archived == true"

    def test_string_with_quotes_is_escaped(self):
        # Double quotes and backslashes in values can't break out.
        assert translate_where({"title": 'hello "world"'}) == 'title == "hello \\"world\\""'

    def test_in_operator(self):
        got = translate_where({"chunk_index": {"$in": [1, 2, 3]}})
        assert got == "chunk_index in [1, 2, 3]"

    def test_in_operator_strings(self):
        got = translate_where({"wing": {"$in": ["a", "b"]}})
        assert got == 'wing in ["a", "b"]'

    def test_and_of_clauses(self):
        got = translate_where({"$and": [{"wing": "p"}, {"room": "r"}]})
        assert got == '(wing == "p" and room == "r")'

    def test_or_of_clauses(self):
        got = translate_where({"$or": [{"wing": "p"}, {"wing": "q"}]})
        assert got == '(wing == "p" or wing == "q")'

    def test_and_with_in(self):
        got = translate_where(
            {
                "$and": [
                    {"source_file": "x"},
                    {"chunk_index": {"$in": [1, 2]}},
                ]
            }
        )
        assert got == '(source_file == "x" and chunk_index in [1, 2])'

    def test_multi_key_without_and_is_rejected(self):
        with pytest.raises(ValueError, match="explicit \\$and"):
            translate_where({"wing": "p", "room": "r"})

    def test_unsupported_operator_is_rejected(self):
        with pytest.raises(ValueError, match="only \\$in"):
            translate_where({"chunk_index": {"$gt": 5}})

    def test_unsupported_top_level_operator_is_rejected(self):
        with pytest.raises(ValueError, match="unsupported top-level"):
            translate_where({"$nor": [{"wing": "x"}]})


# ── end-to-end tests with Milvus Lite ─────────────────────────────────────


def _locate_model_dir() -> Path | None:
    """Same lookup logic as test_embeddings — the conftest redirects HOME."""
    env = os.environ.get("MEMPALACE_TEST_ONNX_DIR")
    if env:
        return Path(env).expanduser()
    try:
        import pwd

        real_home = pwd.getpwuid(os.getuid()).pw_dir
    except Exception:
        return None
    base = Path(real_home)
    for candidate in (
        base / ".cache" / "mempalace" / "onnx",
        base / ".cache" / "chroma" / "onnx_models" / "all-MiniLM-L6-v2",
    ):
        for d in (candidate, candidate / "onnx"):
            if (d / "model.onnx").is_file() and (d / "tokenizer.json").is_file():
                return d
    return None


milvus_e2e_skip = pytest.mark.skipif(
    sys.platform == "win32",
    reason="milvus-lite is not distributed on Windows",
)


@pytest.fixture
def milvus_collection(tmp_path):
    """Fresh Milvus Lite-backed collection keyed to a tmp_path palace."""
    model_dir = _locate_model_dir()
    if model_dir is None:
        pytest.skip("all-MiniLM-L6-v2 ONNX model not cached locally")

    from mempalace.backends.milvus import MilvusBackend
    from mempalace.embeddings import Embedder

    embedder = Embedder(local_dir=model_dir)
    backend = MilvusBackend(embedder=embedder)
    palace_path = str(tmp_path / "palace")
    col = backend.get_or_create_collection(palace_path, "mempalace_drawers")
    try:
        yield backend, palace_path, col
    finally:
        # Close every MilvusClient this backend opened. Without this,
        # milvus-lite's unix socket can linger and the next fixture in
        # the same test session hits "illegal connection params".
        for client in list(backend._clients.values()):
            try:
                client.close()
            except Exception:
                pass
        backend._clients.clear()


@milvus_e2e_skip
class TestMilvusEndToEnd:
    def test_db_file_created_under_palace(self, milvus_collection, tmp_path):
        backend, palace_path, col = milvus_collection
        col.add(ids=["a"], documents=["seed"])
        db_path = Path(palace_path) / "milvus.db"
        assert db_path.is_file()
        assert db_path.stat().st_size > 0

    def test_add_and_count(self, milvus_collection):
        _, _, col = milvus_collection
        col.add(
            ids=["a", "b", "c"],
            documents=["alpha", "bravo", "charlie"],
            metadatas=[{"wing": "w1"}, {"wing": "w2"}, {"wing": "w1"}],
        )
        assert col.count() == 3

    def test_upsert_overwrites(self, milvus_collection):
        _, _, col = milvus_collection
        col.add(ids=["a"], documents=["first"], metadatas=[{"wing": "w"}])
        col.upsert(ids=["a"], documents=["second"], metadatas=[{"wing": "w2"}])
        got = col.get(ids=["a"])
        assert got.ids == ["a"]
        assert got.documents == ["second"]
        assert got.metadatas == [{"wing": "w2"}]
        assert col.count() == 1

    def test_query_returns_verbatim_documents(self, milvus_collection):
        _, _, col = milvus_collection
        col.add(
            ids=["d1", "d2", "d3"],
            documents=[
                "hello world",
                "python programming",
                "vector databases are fun",
            ],
        )
        result = col.query(query_texts=["vector search"], n_results=2)
        assert len(result.ids) == 2
        # Top hit should be the document about vector databases.
        assert "vector databases" in result.documents[0]
        # Distances are cosine distance (0 = identical, > 0 further apart).
        assert all(isinstance(d, float) for d in result.distances)
        assert result.distances == sorted(result.distances)

    def test_query_with_where_filter(self, milvus_collection):
        _, _, col = milvus_collection
        col.add(
            ids=["a", "b", "c"],
            documents=["note one", "note two", "note three"],
            metadatas=[{"wing": "a"}, {"wing": "b"}, {"wing": "a"}],
        )
        result = col.query(
            query_texts=["note"],
            n_results=5,
            where={"wing": "b"},
        )
        assert result.ids == ["b"]
        assert result.metadatas[0]["wing"] == "b"

    def test_query_with_and_filter(self, milvus_collection):
        _, _, col = milvus_collection
        col.add(
            ids=["a", "b", "c"],
            documents=["one", "two", "three"],
            metadatas=[
                {"wing": "w", "room": "r1"},
                {"wing": "w", "room": "r2"},
                {"wing": "w", "room": "r1"},
            ],
        )
        result = col.query(
            query_texts=["query"],
            n_results=10,
            where={"$and": [{"wing": "w"}, {"room": "r1"}]},
        )
        assert set(result.ids) == {"a", "c"}

    def test_get_with_ids(self, milvus_collection):
        _, _, col = milvus_collection
        col.add(
            ids=["a", "b"],
            documents=["alpha", "bravo"],
            metadatas=[{"wing": "a"}, {"wing": "b"}],
        )
        got = col.get(ids=["b"])
        assert got.ids == ["b"]
        assert got.documents == ["bravo"]
        assert got.metadatas[0]["wing"] == "b"

    def test_get_with_in_filter(self, milvus_collection):
        _, _, col = milvus_collection
        col.add(
            ids=["a", "b", "c"],
            documents=["x", "y", "z"],
            metadatas=[{"chunk_index": 0}, {"chunk_index": 1}, {"chunk_index": 2}],
        )
        got = col.get(where={"chunk_index": {"$in": [0, 2]}}, limit=10)
        assert set(got.ids) == {"a", "c"}

    def test_get_respects_include_ids_only(self, milvus_collection):
        _, _, col = milvus_collection
        col.add(ids=["a", "b"], documents=["one", "two"])
        got = col.get(ids=["a", "b"], include=())
        assert set(got.ids) == {"a", "b"}
        assert got.documents == []
        assert got.metadatas == []

    def test_get_empty_ids_returns_empty(self, milvus_collection):
        _, _, col = milvus_collection
        col.add(ids=["a"], documents=["x"])
        got = col.get(ids=[])
        assert got.ids == []

    def test_delete_by_ids(self, milvus_collection):
        _, _, col = milvus_collection
        col.add(ids=["a", "b", "c"], documents=["x", "y", "z"])
        col.delete(ids=["b"])
        remaining = col.get(ids=["a", "b", "c"])
        assert set(remaining.ids) == {"a", "c"}
        assert col.count() == 2

    def test_delete_by_where(self, milvus_collection):
        _, _, col = milvus_collection
        col.add(
            ids=["a", "b", "c"],
            documents=["x", "y", "z"],
            metadatas=[{"wing": "p"}, {"wing": "q"}, {"wing": "p"}],
        )
        col.delete(where={"wing": "p"})
        assert col.count() == 1
        remaining = col.get(ids=["a", "b", "c"])
        assert remaining.ids == ["b"]

    def test_delete_requires_something(self, milvus_collection):
        _, _, col = milvus_collection
        with pytest.raises(ValueError, match="delete requires"):
            col.delete()

    def test_update_merges_metadata(self, milvus_collection):
        _, _, col = milvus_collection
        col.add(
            ids=["a"],
            documents=["first"],
            metadatas=[{"wing": "w", "room": "r1"}],
        )
        col.update(ids=["a"], metadatas=[{"wing": "w", "room": "r2"}])
        got = col.get(ids=["a"])
        assert got.documents == ["first"]
        assert got.metadatas[0]["room"] == "r2"

    def test_update_missing_id_raises(self, milvus_collection):
        _, _, col = milvus_collection
        with pytest.raises(KeyError):
            col.update(ids=["does_not_exist"], metadatas=[{"wing": "x"}])

    def test_backend_rejects_non_cosine_metric(self, milvus_collection):
        backend, palace_path, _ = milvus_collection
        with pytest.raises(ValueError, match="cosine"):
            backend.create_collection(palace_path, "other", hnsw_space="l2")

    def test_get_or_create_is_idempotent(self, milvus_collection):
        backend, palace_path, _ = milvus_collection
        # Second call with same name must not raise.
        col2 = backend.get_or_create_collection(palace_path, "mempalace_drawers")
        assert col2 is not None

    def test_delete_collection_round_trip(self, milvus_collection):
        backend, palace_path, col = milvus_collection
        col.add(ids=["a"], documents=["x"])
        backend.delete_collection(palace_path, "mempalace_drawers")
        # Re-creating must start clean.
        col2 = backend.get_or_create_collection(palace_path, "mempalace_drawers")
        assert col2.count() == 0

    def test_document_over_limit_is_rejected(self, milvus_collection):
        _, _, col = milvus_collection
        from mempalace.backends.milvus import DOCUMENT_MAX_LENGTH

        huge = "x" * (DOCUMENT_MAX_LENGTH + 1)
        with pytest.raises(ValueError, match="chunk before storing"):
            col.add(ids=["big"], documents=[huge])

    def test_reserved_metadata_key_is_rejected(self, milvus_collection):
        _, _, col = milvus_collection
        with pytest.raises(ValueError, match="reserved field"):
            col.add(
                ids=["a"],
                documents=["x"],
                metadatas=[{"id": "clash"}],
            )

    def test_id_over_max_length_is_rejected(self, milvus_collection):
        _, _, col = milvus_collection
        from mempalace.backends.milvus import DRAWER_ID_MAX_LENGTH

        with pytest.raises(ValueError, match="exceeds"):
            col.add(ids=["x" * (DRAWER_ID_MAX_LENGTH + 1)], documents=["doc"])

    def test_empty_id_is_rejected(self, milvus_collection):
        _, _, col = milvus_collection
        with pytest.raises(ValueError, match="non-empty string"):
            col.add(ids=[""], documents=["doc"])

    def test_ragged_input_lists_rejected(self, milvus_collection):
        _, _, col = milvus_collection
        with pytest.raises(ValueError, match="equal length"):
            col.add(ids=["a", "b"], documents=["only one"])

    def test_query_empty_texts_returns_empty(self, milvus_collection):
        _, _, col = milvus_collection
        col.add(ids=["a"], documents=["x"])
        assert col.query(query_texts=[], n_results=5).ids == []

    def test_query_with_distances_only(self, milvus_collection):
        _, _, col = milvus_collection
        col.add(
            ids=["a", "b"],
            documents=["hello", "world"],
        )
        result = col.query(
            query_texts=["hi"],
            n_results=2,
            include=["distances"],
        )
        assert len(result.ids) == 2
        assert result.documents == []
        assert result.metadatas == []
        assert len(result.distances) == 2

    def test_count_on_empty_collection(self, milvus_collection):
        _, _, col = milvus_collection
        assert col.count() == 0

    def test_get_with_no_args_scans_collection(self, milvus_collection):
        _, _, col = milvus_collection
        col.add(ids=["a", "b", "c"], documents=["one", "two", "three"])
        got = col.get(limit=10)
        assert set(got.ids) == {"a", "b", "c"}
        assert len(got.documents) == 3


@milvus_e2e_skip
class TestMilvusBackendSelection:
    def test_backend_not_found_raises(self, tmp_path, monkeypatch):
        """get_collection(create=False) on a missing palace must raise."""
        from mempalace.backends.milvus import MilvusBackend
        from mempalace.embeddings import Embedder

        model_dir = _locate_model_dir()
        if model_dir is None:
            pytest.skip("all-MiniLM-L6-v2 ONNX model not cached locally")

        backend = MilvusBackend(embedder=Embedder(local_dir=model_dir))
        with pytest.raises(FileNotFoundError):
            backend.get_collection(str(tmp_path / "does-not-exist"), "test", create=False)

    def test_create_collection_rejects_duplicate(self, tmp_path):
        from mempalace.backends.milvus import MilvusBackend
        from mempalace.embeddings import Embedder

        model_dir = _locate_model_dir()
        if model_dir is None:
            pytest.skip("all-MiniLM-L6-v2 ONNX model not cached locally")

        backend = MilvusBackend(embedder=Embedder(local_dir=model_dir))
        palace = str(tmp_path / "palace")
        backend.create_collection(palace, "dupe")
        try:
            with pytest.raises(ValueError, match="already exists"):
                backend.create_collection(palace, "dupe")
        finally:
            for c in list(backend._clients.values()):
                try:
                    c.close()
                except Exception:
                    pass
            backend._clients.clear()

    def test_make_default_backend_env_var(self, monkeypatch):
        import mempalace.backends as backends

        monkeypatch.setenv("MEMPALACE_BACKEND", "milvus")
        b = backends.make_default_backend()
        # Don't connect — just assert type.
        from mempalace.backends.milvus import MilvusBackend

        assert isinstance(b, MilvusBackend)

    def test_make_default_backend_defaults_to_chroma(self, monkeypatch):
        import mempalace.backends as backends

        monkeypatch.delenv("MEMPALACE_BACKEND", raising=False)
        b = backends.make_default_backend()
        assert isinstance(b, backends.ChromaBackend)

    def test_make_default_backend_rejects_unknown(self, monkeypatch):
        import mempalace.backends as backends

        monkeypatch.setenv("MEMPALACE_BACKEND", "mysql")
        with pytest.raises(ValueError, match="Unknown MEMPALACE_BACKEND"):
            backends.make_default_backend()

    def test_milvus_backend_attribute_export(self):
        """``from mempalace.backends import MilvusBackend`` must work."""
        from mempalace.backends import MilvusBackend

        assert MilvusBackend.__name__ == "MilvusBackend"

    def test_explicit_uri_override_used(self, tmp_path, monkeypatch):
        """Passing uri= should bypass per-palace-path resolution."""
        from mempalace.backends.milvus import MilvusBackend
        from mempalace.embeddings import Embedder

        model_dir = _locate_model_dir()
        if model_dir is None:
            pytest.skip("all-MiniLM-L6-v2 ONNX model not cached locally")

        uri = str(tmp_path / "shared.db")
        backend = MilvusBackend(uri=uri, embedder=Embedder(local_dir=model_dir))
        try:
            # Different palace paths collapse to the same file when uri is set.
            col1 = backend.get_or_create_collection("/ignored/a", "one")
            col2 = backend.get_or_create_collection("/ignored/b", "two")
            col1.add(ids=["x"], documents=["via first palace path"])
            col2.add(ids=["y"], documents=["via second palace path"])
            assert Path(uri).is_file()
            assert col1.count() == 1
            assert col2.count() == 1
        finally:
            for c in list(backend._clients.values()):
                try:
                    c.close()
                except Exception:
                    pass
            backend._clients.clear()
