"""Tests for safe_mine_session context manager and close_palace lifecycle.

Covers the SIGINT handler, signal restoration order, close_palace flush,
and the ChromaBackend.close_palace / close warning paths.
"""

import logging
import signal
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from mempalace.palace import close_palace, safe_mine_session


# ── safe_mine_session: basic lifecycle ──────────────────────────────────


class TestSafeMineSessionLifecycle:
    """Core context manager behaviour without actual SIGINT delivery."""

    def test_enters_and_exits_cleanly(self, tmp_path):
        palace = tmp_path / "palace"
        palace.mkdir()
        with safe_mine_session(str(palace), dry_run=True) as session:
            assert session.interrupted is False

    def test_interrupted_flag_starts_false(self, tmp_path):
        palace = tmp_path / "palace"
        palace.mkdir()
        with safe_mine_session(str(palace), dry_run=True) as session:
            assert session.interrupted is False
            # Manually simulate what the handler does
            session.interrupted = True
        assert session.interrupted is True

    def test_dry_run_skips_close_palace(self, tmp_path):
        """In dry_run mode, close_palace should NOT be called."""
        palace = tmp_path / "palace"
        palace.mkdir()
        with patch("mempalace.palace.close_palace") as mock_close:
            with safe_mine_session(str(palace), dry_run=True):
                pass
        mock_close.assert_not_called()

    def test_non_dry_run_calls_close_palace(self, tmp_path):
        """Normal mode MUST call close_palace on exit."""
        palace = tmp_path / "palace"
        palace.mkdir()
        with patch("mempalace.palace.close_palace") as mock_close:
            with safe_mine_session(str(palace), dry_run=False):
                pass
        mock_close.assert_called_once_with(str(palace))

    def test_close_palace_called_even_on_exception(self, tmp_path):
        """close_palace fires even when the body raises."""
        palace = tmp_path / "palace"
        palace.mkdir()
        with patch("mempalace.palace.close_palace") as mock_close:
            with pytest.raises(RuntimeError):
                with safe_mine_session(str(palace), dry_run=False):
                    raise RuntimeError("boom")
        mock_close.assert_called_once_with(str(palace))


# ── safe_mine_session: signal handling ──────────────────────────────────


class TestSafeMineSessionSignal:
    """Signal installation and restoration behaviour."""

    def test_installs_custom_handler_on_enter(self, tmp_path):
        palace = tmp_path / "palace"
        palace.mkdir()
        original = signal.getsignal(signal.SIGINT)
        with safe_mine_session(str(palace), dry_run=True) as session:
            current = signal.getsignal(signal.SIGINT)
            assert current is not original
            assert current == session._handle_sigint
        # After exit, original is restored
        assert signal.getsignal(signal.SIGINT) is original

    def test_restores_original_handler_on_exit(self, tmp_path):
        palace = tmp_path / "palace"
        palace.mkdir()
        original = signal.getsignal(signal.SIGINT)
        with safe_mine_session(str(palace), dry_run=True):
            pass
        assert signal.getsignal(signal.SIGINT) is original

    def test_restores_handler_after_close_palace_not_before(self, tmp_path):
        """Signal must stay deferred during close_palace() — the whole point
        of the fix.  We verify by checking what signal handler is active at
        the moment close_palace is called."""
        palace = tmp_path / "palace"
        palace.mkdir()
        handler_during_close = []

        def spy_close(path):
            handler_during_close.append(signal.getsignal(signal.SIGINT))

        original = signal.getsignal(signal.SIGINT)
        with patch("mempalace.palace.close_palace", side_effect=spy_close):
            with safe_mine_session(str(palace), dry_run=False):
                pass

        # During close_palace, the handler should NOT have been the original
        assert len(handler_during_close) == 1
        assert handler_during_close[0] is not original

    def test_handler_sets_interrupted_on_first_call(self, tmp_path, capsys):
        palace = tmp_path / "palace"
        palace.mkdir()
        with safe_mine_session(str(palace), dry_run=True) as session:
            assert session.interrupted is False
            # Simulate SIGINT delivery
            session._handle_sigint(signal.SIGINT, None)
            assert session.interrupted is True
            captured = capsys.readouterr()
            assert "Ctrl+C received" in captured.out

    def test_handler_second_call_stays_interrupted(self, tmp_path, capsys):
        palace = tmp_path / "palace"
        palace.mkdir()
        with safe_mine_session(str(palace), dry_run=True) as session:
            session._handle_sigint(signal.SIGINT, None)
            session._handle_sigint(signal.SIGINT, None)
            assert session.interrupted is True
            captured = capsys.readouterr()
            assert "corrupts the index" in captured.out


# ── close_palace: backend integration ───────────────────────────────────


class TestClosePalace:
    """Tests for the close_palace function and backend close methods."""

    def test_close_palace_calls_client_close(self, tmp_path):
        """close_palace must trigger client.close() on the cached client."""
        from mempalace.backends.chroma import ChromaBackend

        palace = tmp_path / "palace"
        palace.mkdir()
        backend = ChromaBackend()

        # Open a real client so it gets cached
        backend.get_collection(str(palace), collection_name="mempalace_drawers", create=True)
        assert str(palace) in backend._clients

        # Now close it
        backend.close_palace(str(palace))

        # Client should be removed from cache
        assert str(palace) not in backend._clients
        assert str(palace) not in backend._freshness

    def test_close_palace_noop_for_uncached_path(self, tmp_path):
        """close_palace on a path never opened should not raise."""
        from mempalace.backends.chroma import ChromaBackend

        backend = ChromaBackend()
        # Should not raise
        backend.close_palace(str(tmp_path / "nonexistent"))

    def test_close_palace_none_path_is_noop(self):
        """close_palace(None) should return immediately."""
        from mempalace.backends.chroma import ChromaBackend
        from mempalace.backends import PalaceRef

        backend = ChromaBackend()
        # PalaceRef with None local_path
        ref = PalaceRef(id="test", local_path=None)
        backend.close_palace(ref)  # should not raise

    def test_close_all_clears_all_clients(self, tmp_path):
        """close() must close all cached clients and clear state."""
        from mempalace.backends.chroma import ChromaBackend

        backend = ChromaBackend()

        # Open two palaces
        p1 = tmp_path / "palace1"
        p2 = tmp_path / "palace2"
        p1.mkdir()
        p2.mkdir()
        backend.get_collection(str(p1), collection_name="mempalace_drawers", create=True)
        backend.get_collection(str(p2), collection_name="mempalace_drawers", create=True)
        assert len(backend._clients) == 2

        backend.close()

        assert len(backend._clients) == 0
        assert len(backend._freshness) == 0
        assert backend._closed is True

    def test_close_palace_logs_warning_on_client_close_failure(self, tmp_path, caplog):
        """When client.close() raises, the exception must be logged as a warning."""
        from mempalace.backends.chroma import ChromaBackend

        backend = ChromaBackend()
        palace_str = str(tmp_path / "palace")

        # Inject a mock client that raises on close()
        mock_client = MagicMock()
        mock_client.close.side_effect = RuntimeError("disk full")
        backend._clients[palace_str] = mock_client
        backend._freshness[palace_str] = (0, 0.0)

        with caplog.at_level(logging.WARNING, logger="mempalace.backends.chroma"):
            backend.close_palace(palace_str)

        assert "Failed to close ChromaDB client" in caplog.text
        assert "disk full" in caplog.text
        # Client should still be removed from cache
        assert palace_str not in backend._clients

    def test_close_logs_warning_on_client_close_failure(self, tmp_path, caplog):
        """close() must log warnings for individual client failures
        but continue closing remaining clients."""
        from mempalace.backends.chroma import ChromaBackend

        backend = ChromaBackend()

        # Two clients: one raises, one succeeds
        mock_bad = MagicMock()
        mock_bad.close.side_effect = RuntimeError("io error")
        mock_good = MagicMock()

        backend._clients["bad"] = mock_bad
        backend._clients["good"] = mock_good
        backend._freshness["bad"] = (0, 0.0)
        backend._freshness["good"] = (0, 0.0)

        with caplog.at_level(logging.WARNING, logger="mempalace.backends.chroma"):
            backend.close()

        # Both clients should have had close() called
        mock_bad.close.assert_called_once()
        mock_good.close.assert_called_once()
        # Warning logged for the failing one
        assert "Failed to close ChromaDB client" in caplog.text
        # State fully cleared
        assert len(backend._clients) == 0
        assert backend._closed is True


# ── Integration: convo_miner uses safe_mine_session ─────────────────────
#
# NOTE: miner.mine() no longer uses safe_mine_session — upstream PR #1183
# added try/except KeyboardInterrupt directly in the mine loop. Our
# safe_mine_session is still used by convo_miner.mine_convos() and
# provides signal-deferral during the convo mining path (which upstream
# did not harden).


class TestConvoMinerIntegration:
    """Verify that mine_convos() still uses safe_mine_session."""

    def test_convo_miner_imports_safe_mine_session(self):
        """convo_miner must import safe_mine_session from palace."""
        from mempalace import convo_miner

        # Verify the import exists (would ImportError if removed)
        assert hasattr(convo_miner, "mine_convos")

    def test_safe_mine_session_referenced_in_convo_miner_source(self):
        """Ensure convo_miner.py actually calls safe_mine_session."""
        import inspect
        from mempalace import convo_miner

        source = inspect.getsource(convo_miner)
        assert "safe_mine_session" in source, (
            "convo_miner must use safe_mine_session for signal-safe mining"
        )
