"""Tests for NLP-related CLI additions."""

import argparse
from unittest.mock import patch

import pytest

from mempalace.cli import cmd_nlp, main


# ── --nlp-backend flag ─────────────────────────────────────────────


def test_nlp_backend_flag_accepted():
    """--nlp-backend should be accepted by the parser without error."""
    with patch("sys.argv", ["mempalace", "--nlp-backend", "legacy", "status"]):
        with patch("mempalace.cli.cmd_status"):
            main()


def test_nlp_backend_flag_choices():
    """--nlp-backend should only accept valid backend levels."""
    with patch("sys.argv", ["mempalace", "--nlp-backend", "invalid_backend", "status"]):
        with pytest.raises(SystemExit):
            main()


# ── nlp subcommand ─────────────────────────────────────────────────


def test_nlp_subcommand_exists():
    """'nlp' should be a recognized subcommand."""
    with patch("sys.argv", ["mempalace", "nlp", "status"]):
        with patch("mempalace.cli._nlp_status") as mock_status:
            main()
            mock_status.assert_called_once()


def test_nlp_status_runs(capsys):
    """'nlp status' should print status without error."""
    with patch("mempalace.cli._nlp_status") as mock_status:
        args = argparse.Namespace(nlp_action="status")
        cmd_nlp(args)
        mock_status.assert_called_once()


def test_nlp_install_runs():
    """'nlp install' should call _nlp_install."""
    with patch("mempalace.cli._nlp_install") as mock_install:
        args = argparse.Namespace(nlp_action="install", backend="spacy")
        cmd_nlp(args)
        mock_install.assert_called_once_with(args)


def test_nlp_remove_runs():
    """'nlp remove' should call _nlp_remove."""
    with patch("mempalace.cli._nlp_remove") as mock_remove:
        args = argparse.Namespace(nlp_action="remove", model_id="spacy-xx-ent-wiki-sm")
        cmd_nlp(args)
        mock_remove.assert_called_once_with(args)


def test_nlp_verify_runs():
    """'nlp verify' should call _nlp_verify."""
    with patch("mempalace.cli._nlp_verify") as mock_verify:
        args = argparse.Namespace(nlp_action="verify")
        cmd_nlp(args)
        mock_verify.assert_called_once()


def test_nlp_no_action(capsys):
    """'nlp' with no action should print usage."""
    args = argparse.Namespace(nlp_action=None)
    cmd_nlp(args)
    captured = capsys.readouterr()
    assert "status" in captured.out


def test_nlp_status_output(capsys):
    """_nlp_status should produce readable output."""
    from mempalace.cli import _nlp_status

    _nlp_status()
    captured = capsys.readouterr()
    assert "MemPalace NLP Status" in captured.out
    assert "Active backend" in captured.out
    assert "legacy" in captured.out
