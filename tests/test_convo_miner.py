"""Tests for mempalace.convo_miner — conversation ingestion."""

import os
import shutil

import chromadb
import pytest

from mempalace.convo_miner import (
    _chunk_by_exchange,
    _chunk_by_paragraph,
    chunk_exchanges,
    detect_convo_room,
    mine_convos,
    scan_convos,
)


class TestChunkExchanges:
    def test_exchange_markers(self):
        content = (
            "> What is artificial intelligence and how does it work?\n"
            "AI is the simulation of human intelligence by machines and software systems.\n\n"
            "> Why is it important in modern technology?\n"
            "Because it automates complex tasks and enables new capabilities.\n\n"
            "> How do large language models work in practice?\n"
            "They use transformer architectures trained on vast amounts of text data.\n"
        )
        chunks = chunk_exchanges(content)
        assert len(chunks) >= 2
        assert all("content" in c and "chunk_index" in c for c in chunks)

    def test_no_markers_falls_to_paragraph(self):
        content = (
            "First paragraph about artificial intelligence and how it transforms modern technology.\n\n"
            "Second paragraph about memory systems and their role in knowledge management.\n\n"
            "Third paragraph about semantic search and vector embeddings in databases."
        )
        chunks = chunk_exchanges(content)
        assert len(chunks) >= 1

    def test_empty_content(self):
        assert chunk_exchanges("") == []
        assert chunk_exchanges("   ") == []


class TestChunkByExchange:
    def test_pairs_user_and_response(self):
        lines = [
            "> What is memory?",
            "Memory stores information.",
            "",
            "> Why does it matter?",
            "It provides context for decisions.",
        ]
        chunks = _chunk_by_exchange(lines)
        assert len(chunks) == 2
        assert "> What is memory?" in chunks[0]["content"]
        assert "Memory stores" in chunks[0]["content"]

    def test_skips_short_chunks(self):
        lines = ["> Hi", "Ok"]
        chunks = _chunk_by_exchange(lines)
        assert len(chunks) == 0

    def test_separator_lines(self):
        lines = [
            "> Question one",
            "Long answer that has enough content to be meaningful for testing purposes.",
            "---",
            "> Question two",
            "Another long answer that should be in a separate chunk for testing.",
        ]
        chunks = _chunk_by_exchange(lines)
        assert len(chunks) == 2


class TestChunkByParagraph:
    def test_double_newline_split(self):
        content = (
            "First paragraph that is long enough to pass minimum size filter easily.\n\n"
            "Second paragraph that is also long enough to pass minimum size filter."
        )
        chunks = _chunk_by_paragraph(content)
        assert len(chunks) == 2

    def test_long_single_block_chunks_by_lines(self):
        content = "\n".join(f"Line {i} with enough content to be meaningful." for i in range(30))
        chunks = _chunk_by_paragraph(content)
        assert len(chunks) >= 1


class TestDetectConvoRoom:
    @pytest.mark.parametrize(
        "content, expected",
        [
            ("We need to fix the python code bug in the api", "technical"),
            ("The architecture design pattern for our service layer", "architecture"),
            ("Let's plan the roadmap and prioritize the sprint backlog", "planning"),
            ("We decided to switch to GraphQL, picked that approach", "decisions"),
            ("The problem is broken, crash failed with issue", "problems"),
            ("The weather is nice and the sky is blue today", "general"),
        ],
    )
    def test_topic_detection(self, content, expected):
        assert detect_convo_room(content) == expected


class TestScanConvos:
    def test_finds_txt_files(self, sample_convos):
        files = scan_convos(str(sample_convos))
        assert len(files) >= 1
        assert any(f.name == "chat.txt" for f in files)

    def test_skips_hidden_dirs(self, tmp_path):
        d = tmp_path / "convos"
        d.mkdir()
        git = d / ".git"
        git.mkdir()
        (git / "config.txt").write_text("git stuff")
        (d / "real.txt").write_text("real content")
        files = scan_convos(str(d))
        assert all(".git" not in str(f) for f in files)

    def test_empty_dir(self, tmp_path):
        d = tmp_path / "empty"
        d.mkdir()
        assert scan_convos(str(d)) == []


class TestMineConvosIntegration:
    @pytest.mark.integration
    def test_mines_and_stores(self, sample_convos, palace_path):
        mine_convos(str(sample_convos), palace_path, wing="test_convos")
        client = chromadb.PersistentClient(path=palace_path)
        col = client.get_collection("mempalace_drawers")
        assert col.count() >= 2

    @pytest.mark.integration
    def test_dry_run_stores_nothing(self, sample_convos, palace_path, capsys):
        mine_convos(str(sample_convos), palace_path, wing="test_convos", dry_run=True)
        assert not os.path.exists(os.path.join(palace_path, "chroma.sqlite3"))

    @pytest.mark.integration
    def test_skip_already_mined(self, sample_convos, palace_path):
        mine_convos(str(sample_convos), palace_path, wing="w")
        client = chromadb.PersistentClient(path=palace_path)
        count1 = client.get_collection("mempalace_drawers").count()
        from mempalace.palace_db import reset
        reset()
        mine_convos(str(sample_convos), palace_path, wing="w")
        count2 = client.get_collection("mempalace_drawers").count()
        assert count2 == count1

    @pytest.mark.integration
    def test_limit_files(self, tmp_path, palace_path):
        d = tmp_path / "multi"
        d.mkdir()
        for i in range(5):
            (d / f"chat{i}.txt").write_text(
                f"> Q{i} about something interesting?\nAnswer {i} with enough content to pass.\n\n"
                f"> Follow up {i}?\nMore detail on the topic {i}.\n"
            )
        mine_convos(str(d), palace_path, wing="w", limit=2)
