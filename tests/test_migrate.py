"""Tests for destructive-operation safety in mempalace.migrate."""

import os
from unittest.mock import MagicMock, patch

from mempalace.migrate import migrate


def test_migrate_requires_palace_database(tmp_path, capsys):
    palace_dir = tmp_path / "palace"
    palace_dir.mkdir()

    result = migrate(str(palace_dir))

    out = capsys.readouterr().out
    assert result is False
    assert "No palace database found" in out


def test_migrate_aborts_without_confirmation(tmp_path, capsys):
    palace_dir = tmp_path / "palace"
    palace_dir.mkdir()
    # Presence of chroma.sqlite3 is the safety gate; validity is mocked below.
    (palace_dir / "chroma.sqlite3").write_text("db")

    read_client = MagicMock()
    read_client._system = MagicMock()
    read_backend = MagicMock()
    read_backend._clients = {str(palace_dir): read_client}
    read_backend.get_collection.side_effect = Exception("unreadable")
    mock_backend_cls = MagicMock(return_value=read_backend)
    mock_backend_cls.backend_version.return_value = "0.6.0"

    with (
        patch("mempalace.backends.chroma.ChromaBackend", mock_backend_cls),
        patch("mempalace.migrate.detect_chromadb_version", return_value="0.5.x"),
        patch(
            "mempalace.migrate.extract_drawers_from_sqlite",
            return_value=[{"id": "id1", "document": "doc", "metadata": {"wing": "w", "room": "r"}}],
        ),
        patch("builtins.input", return_value="n"),
        patch("mempalace.migrate.shutil.copytree") as mock_copytree,
        patch("mempalace.migrate.shutil.rmtree") as mock_rmtree,
    ):
        result = migrate(str(palace_dir))

    out = capsys.readouterr().out
    assert result is False
    assert "Aborted." in out
    mock_copytree.assert_not_called()
    mock_rmtree.assert_not_called()


def test_migrate_retries_palace_swap_after_windows_lock(tmp_path, capsys):
    palace_dir = tmp_path / "palace"
    palace_dir.mkdir()
    (palace_dir / "chroma.sqlite3").write_text("db")

    read_client = MagicMock()
    read_client._system = MagicMock()
    read_backend = MagicMock()
    read_backend._clients = {str(palace_dir): read_client}
    read_backend.get_collection.side_effect = Exception("unreadable")

    temp_collection = MagicMock()
    temp_collection.count.return_value = 1
    temp_collection._collection = MagicMock()
    temp_collection._collection._client = MagicMock()
    temp_collection._collection._client._system = MagicMock()

    write_client = MagicMock()
    write_client._system = MagicMock()
    write_backend = MagicMock()
    write_backend._clients = {"C:\\temp\\migrated-palace": write_client}
    write_backend.get_or_create_collection.return_value = temp_collection

    mock_backend_cls = MagicMock(side_effect=[read_backend, write_backend])
    mock_backend_cls.backend_version.return_value = "0.6.0"

    with (
        patch("mempalace.backends.chroma.ChromaBackend", mock_backend_cls),
        patch("mempalace.migrate.detect_chromadb_version", return_value="1.x"),
        patch(
            "mempalace.migrate.extract_drawers_from_sqlite",
            return_value=[{"id": "id1", "document": "doc", "metadata": {"wing": "w", "room": "r"}}],
        ),
        patch("mempalace.migrate.shutil.copytree"),
        patch("tempfile.mkdtemp", return_value="C:\\temp\\migrated-palace"),
        patch(
            "mempalace.migrate.shutil.rmtree",
            side_effect=[PermissionError("locked"), None],
        ) as mock_rmtree,
        patch("mempalace.migrate.shutil.move") as mock_move,
        patch("mempalace.migrate.gc.collect"),
        patch("mempalace.migrate.time.sleep") as mock_sleep,
    ):
        result = migrate(str(palace_dir), confirm=True)

    out = capsys.readouterr().out
    assert result is True
    assert "Waiting for filesystem handles to release" in out
    assert mock_rmtree.call_count == 2
    mock_move.assert_called_once_with("C:\\temp\\migrated-palace", os.path.abspath(str(palace_dir)))
    assert mock_sleep.called
