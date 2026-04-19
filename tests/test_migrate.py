"""Tests for destructive-operation safety in mempalace.migrate."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

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

    mock_chromadb = SimpleNamespace(
        __version__="0.6.0",
        PersistentClient=MagicMock(side_effect=Exception("unreadable")),
    )

    with (
        patch.dict("sys.modules", {"chromadb": mock_chromadb}),
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


def test_migrate_restores_palace_on_swap_failure(tmp_path, capsys):
    """If shutil.move fails mid-swap (e.g. cross-device), restore from the
    pre-migrate backup so the user never ends up with a lost palace.

    Reproducer for the data-loss path where ``shutil.rmtree(palace_path)``
    succeeds but the subsequent ``shutil.move(temp_palace, palace_path)``
    raises — leaving the palace directory gone with no rollback.
    """
    palace_dir = tmp_path / "palace"
    palace_dir.mkdir()
    (palace_dir / "chroma.sqlite3").write_text("dummy db")
    # Sentinel file we verify survives the failed swap via backup restore.
    (palace_dir / "sentinel.txt").write_text("original")

    mock_col = MagicMock()
    mock_col.count.return_value = 1
    mock_backend = MagicMock()
    # First call (readability probe) raises → enters migration path.
    mock_backend.get_collection.side_effect = Exception("unreadable")
    mock_backend.get_or_create_collection.return_value = mock_col

    backend_factory = MagicMock(return_value=mock_backend)
    backend_factory.backend_version = MagicMock(return_value="1.5.4")

    with (
        patch("mempalace.backends.chroma.ChromaBackend", backend_factory),
        patch("mempalace.migrate.detect_chromadb_version", return_value="0.5.x"),
        patch(
            "mempalace.migrate.extract_drawers_from_sqlite",
            return_value=[
                {"id": "id1", "document": "doc", "metadata": {"wing": "w", "room": "r"}}
            ],
        ),
        patch("mempalace.migrate.confirm_destructive_action", return_value=True),
        patch(
            "mempalace.migrate.shutil.move",
            side_effect=OSError("Invalid cross-device link"),
        ),
        pytest.raises(OSError),
    ):
        migrate(str(palace_dir))

    err = capsys.readouterr().err
    assert "swap failed mid-flight" in err
    assert "Restoring palace from backup" in err

    # Palace directory restored with original contents.
    assert palace_dir.is_dir(), "palace directory missing after rollback"
    sentinel = palace_dir / "sentinel.txt"
    assert sentinel.is_file(), "sentinel file not restored from backup"
    assert sentinel.read_text() == "original", "restored contents do not match original"
    # Backup remains on disk for post-mortem.
    backups = [p for p in tmp_path.iterdir() if p.name.startswith("palace.pre-migrate.")]
    assert backups, "backup directory missing after rollback"
