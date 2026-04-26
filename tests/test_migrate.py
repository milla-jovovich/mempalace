"""Tests for destructive-operation safety in mempalace.migrate."""

from types import SimpleNamespace
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



class TestMigrateCheckpointsToRecovery:
    """Phase D — move existing topic=checkpoint drawers from the main
    collection to the dedicated session-recovery collection. Idempotent;
    safe to run multiple times."""

    def _seed_main(self, palace_path):
        from mempalace.palace import get_collection

        main = get_collection(palace_path, create=True)
        main.add(
            ids=["chk1", "chk2", "auto1", "content1", "content2"],
            documents=[
                "CHECKPOINT:2026-04-25 alpha",
                "CHECKPOINT:2026-04-25 beta",
                "auto-save legacy entry gamma",
                "Substantive content about the auth module.",
                "Another content drawer about migrations.",
            ],
            metadatas=[
                {"topic": "checkpoint", "wing": "wing_session-hook"},
                {"topic": "checkpoint", "wing": "wing_session-hook"},
                {"topic": "auto-save", "wing": "wing_session-hook"},
                {"topic": "general", "wing": "project_a"},
                {"topic": "musings", "wing": "project_a"},
            ],
        )
        return main

    def test_migrate_moves_checkpoints(self, tmp_path):
        from mempalace.migrate import migrate_checkpoints_to_recovery
        from mempalace.palace import get_collection, get_session_recovery_collection

        palace_path = str(tmp_path / "palace")
        self._seed_main(palace_path)

        moved = migrate_checkpoints_to_recovery(palace_path)
        assert moved == 3

        main = get_collection(palace_path, create=True)
        recovery = get_session_recovery_collection(palace_path, create=True)
        assert main.count() == 2
        assert recovery.count() == 3

    def test_migrate_is_idempotent(self, tmp_path):
        from mempalace.migrate import migrate_checkpoints_to_recovery
        from mempalace.palace import get_collection, get_session_recovery_collection

        palace_path = str(tmp_path / "palace")
        self._seed_main(palace_path)

        first = migrate_checkpoints_to_recovery(palace_path)
        second = migrate_checkpoints_to_recovery(palace_path)

        assert first == 3
        assert second == 0

        main = get_collection(palace_path, create=True)
        recovery = get_session_recovery_collection(palace_path, create=True)
        assert main.count() == 2
        assert recovery.count() == 3

    def test_migrate_preserves_drawer_ids_and_metadata(self, tmp_path):
        from mempalace.migrate import migrate_checkpoints_to_recovery
        from mempalace.palace import get_session_recovery_collection

        palace_path = str(tmp_path / "palace")
        self._seed_main(palace_path)

        migrate_checkpoints_to_recovery(palace_path)

        recovery = get_session_recovery_collection(palace_path, create=True)
        chk1 = recovery.get(ids=["chk1"], include=["documents", "metadatas"])
        assert chk1["ids"] == ["chk1"]
        assert chk1["documents"][0] == "CHECKPOINT:2026-04-25 alpha"
        assert chk1["metadatas"][0].get("topic") == "checkpoint"
        assert chk1["metadatas"][0].get("wing") == "wing_session-hook"

    def test_migrate_handles_legacy_auto_save_topic(self, tmp_path):
        from mempalace.migrate import migrate_checkpoints_to_recovery
        from mempalace.palace import get_session_recovery_collection

        palace_path = str(tmp_path / "palace")
        self._seed_main(palace_path)

        migrate_checkpoints_to_recovery(palace_path)

        recovery = get_session_recovery_collection(palace_path, create=True)
        auto = recovery.get(ids=["auto1"], include=["metadatas"])
        assert auto["ids"] == ["auto1"]
        assert auto["metadatas"][0].get("topic") == "auto-save"

    def test_migrate_no_checkpoints_returns_zero(self, tmp_path):
        from mempalace.migrate import migrate_checkpoints_to_recovery
        from mempalace.palace import get_collection

        palace_path = str(tmp_path / "palace")
        main = get_collection(palace_path, create=True)
        main.add(
            ids=["c1"],
            documents=["just content"],
            metadatas=[{"topic": "general"}],
        )

        moved = migrate_checkpoints_to_recovery(palace_path)
        assert moved == 0
        assert main.count() == 1

    def test_migrate_no_palace_returns_zero(self, tmp_path):
        from mempalace.migrate import migrate_checkpoints_to_recovery

        moved = migrate_checkpoints_to_recovery(str(tmp_path / "nope"))
        assert moved == 0
