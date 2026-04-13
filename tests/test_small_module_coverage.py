"""Coverage-focused tests for small modules and edge branches.

These tests close out low-level glue and defensive branches with direct,
deterministic checks so the remaining coverage work can stay focused on the
larger integration modules.
"""

import json
import runpy
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from mempalace.backends.base import BaseCollection
from mempalace.backends.chroma import ChromaBackend, _fix_blob_seq_ids
from mempalace.config import MempalaceConfig, sanitize_content, sanitize_name
from mempalace.palace import file_already_mined


class _NotImplementedCollection(BaseCollection):
    """Concrete subclass that intentionally delegates to the abstract stubs."""

    def add(self, *, documents, ids, metadatas=None):
        return BaseCollection.add(self, documents=documents, ids=ids, metadatas=metadatas)

    def upsert(self, *, documents, ids, metadatas=None):
        return BaseCollection.upsert(self, documents=documents, ids=ids, metadatas=metadatas)

    def query(self, **kwargs):
        return BaseCollection.query(self, **kwargs)

    def get(self, **kwargs):
        return BaseCollection.get(self, **kwargs)

    def delete(self, **kwargs):
        return BaseCollection.delete(self, **kwargs)

    def count(self):
        return BaseCollection.count(self)


def test_python_m_entrypoint_invokes_cli_main(monkeypatch):
    fake_cli = types.ModuleType("mempalace.cli")
    calls = []
    fake_cli.main = lambda: calls.append("called")
    monkeypatch.setitem(sys.modules, "mempalace.cli", fake_cli)

    runpy.run_module("mempalace.__main__", run_name="__main__")

    assert calls == ["called"]


def test_base_collection_stub_methods_raise_not_implemented():
    collection = _NotImplementedCollection()

    with pytest.raises(NotImplementedError):
        collection.add(documents=["doc"], ids=["1"])
    with pytest.raises(NotImplementedError):
        collection.upsert(documents=["doc"], ids=["1"])
    with pytest.raises(NotImplementedError):
        collection.query(query_texts=["q"])
    with pytest.raises(NotImplementedError):
        collection.get(ids=["1"])
    with pytest.raises(NotImplementedError):
        collection.delete(ids=["1"])
    with pytest.raises(NotImplementedError):
        collection.count()


@pytest.mark.parametrize(
    ("value", "field_name", "message"),
    [
        ("", "wing", "non-empty string"),
        ("x" * 129, "room", "maximum length"),
        ("../secret", "name", "path characters"),
        ("bad/name", "name", "path characters"),
        ("bad\0name", "name", "null bytes"),
        ("$invalid", "name", "invalid characters"),
    ],
)
def test_sanitize_name_rejects_invalid_inputs(value, field_name, message):
    with pytest.raises(ValueError, match=message):
        sanitize_name(value, field_name)


@pytest.mark.parametrize(
    ("value", "message"),
    [
        ("", "non-empty string"),
        ("x" * 100_001, "maximum length"),
        ("bad\0text", "null bytes"),
    ],
)
def test_sanitize_content_rejects_invalid_inputs(value, message):
    with pytest.raises(ValueError, match=message):
        sanitize_content(value)


def test_config_write_tolerates_missing_chmod_support(monkeypatch, tmp_path):
    cfg = MempalaceConfig(config_dir=str(tmp_path / "config"))

    def _boom(*args, **kwargs):
        raise NotImplementedError

    # Both the directory chmod and the config-file chmod are advisory only.
    monkeypatch.setattr(Path, "chmod", _boom)

    result = cfg.set_hook_setting("silent_save", False)

    assert result.exists()
    assert json.loads(result.read_text(encoding="utf-8"))["hooks"]["silent_save"] is False


def test_file_already_mined_returns_false_on_collection_error():
    collection = MagicMock()
    collection.get.side_effect = RuntimeError("backend unavailable")

    assert file_already_mined(collection, "/tmp/demo.txt") is False


def test_fix_blob_seq_ids_logs_and_returns_when_sqlite_open_fails():
    with patch("mempalace.backends.chroma.os.path.isfile", return_value=True), patch(
        "mempalace.backends.chroma.sqlite3.connect",
        side_effect=RuntimeError("cannot open"),
    ), patch("mempalace.backends.chroma.logger.exception") as mock_log:
        _fix_blob_seq_ids("/tmp/palace")

    mock_log.assert_called_once()


def test_chroma_backend_create_tolerates_chmod_error(tmp_path, monkeypatch):
    palace_path = tmp_path / "palace"

    class _FakeClient:
        def __init__(self, path):
            self.path = path

        def get_or_create_collection(self, collection_name, metadata):
            assert collection_name == "mempalace_drawers"
            assert metadata == {"hnsw:space": "cosine"}
            return MagicMock()

    monkeypatch.setattr("mempalace.backends.chroma.os.chmod", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("no chmod")))
    monkeypatch.setattr("mempalace.backends.chroma.chromadb.PersistentClient", _FakeClient)
    monkeypatch.setattr("mempalace.backends.chroma._fix_blob_seq_ids", lambda path: None)

    collection = ChromaBackend().get_collection(str(palace_path), "mempalace_drawers", create=True)

    assert palace_path.is_dir()
    assert collection.count is not None
