"""Unit tests for convo_miner pure functions (no chromadb needed)."""

import contextlib

from mempalace.convo_miner import (
    _file_chunks_locked,
    chunk_exchanges,
    detect_convo_room,
    scan_convos,
)


class TestChunkExchanges:
    def test_exchange_chunking(self):
        content = (
            "> What is memory?\n"
            "Memory is persistence of information over time.\n\n"
            "> Why does it matter?\n"
            "It enables continuity across sessions and conversations.\n\n"
            "> How do we build it?\n"
            "With structured storage and retrieval mechanisms.\n"
        )
        chunks = chunk_exchanges(content)
        assert len(chunks) >= 2
        assert all("content" in c and "chunk_index" in c for c in chunks)

    def test_paragraph_fallback(self):
        """Content without '>' lines falls back to paragraph chunking."""
        content = (
            "This is a long paragraph about memory systems. " * 10 + "\n\n"
            "This is another paragraph about storage. " * 10 + "\n\n"
            "And a third paragraph about retrieval. " * 10
        )
        chunks = chunk_exchanges(content)
        assert len(chunks) >= 2

    def test_paragraph_line_group_fallback(self):
        """Long content with no paragraph breaks chunks by line groups."""
        lines = [f"Line {i}: some content that is meaningful" for i in range(60)]
        content = "\n".join(lines)
        chunks = chunk_exchanges(content)
        assert len(chunks) >= 1

    def test_empty_content(self):
        chunks = chunk_exchanges("")
        assert chunks == []

    def test_short_content_skipped(self):
        chunks = chunk_exchanges("> hi\nbye")
        # Too short to produce chunks (below MIN_CHUNK_SIZE)
        assert isinstance(chunks, list)

    def test_long_ai_response_not_truncated(self):
        """AI responses longer than 8 lines must be stored in full (verbatim principle)."""
        lines = [f"Step {i}: important detail that must be stored" for i in range(1, 14)]
        content = "> How do I implement authentication?\n" + "\n".join(lines)
        chunks = chunk_exchanges(content)
        assert len(chunks) >= 1
        stored = chunks[0]["content"]
        # All 13 lines must be present — none silently dropped
        for i in range(1, 14):
            assert f"Step {i}:" in stored, f"Step {i} was truncated and not stored"


class TestDetectConvoRoom:
    def test_technical_room(self):
        content = "Let me debug this python function and fix the code error in the api"
        assert detect_convo_room(content) == "technical"

    def test_planning_room(self):
        content = "We need to plan the roadmap for the next sprint and set milestone deadlines"
        assert detect_convo_room(content) == "planning"

    def test_architecture_room(self):
        content = "The architecture uses a service layer with component interface and module design"
        assert detect_convo_room(content) == "architecture"

    def test_decisions_room(self):
        content = "We decided to switch and migrated to the new framework after we chose it"
        assert detect_convo_room(content) == "decisions"

    def test_general_fallback(self):
        content = "Hello, how are you doing today? The weather is nice."
        assert detect_convo_room(content) == "general"


class TestScanConvos:
    def test_scan_finds_txt_and_md(self, tmp_path):
        (tmp_path / "chat.txt").write_text("hello", encoding="utf-8")
        (tmp_path / "notes.md").write_text("world", encoding="utf-8")
        (tmp_path / "image.png").write_bytes(b"fake")
        files = scan_convos(str(tmp_path))
        extensions = {f.suffix for f in files}
        assert ".txt" in extensions
        assert ".md" in extensions
        assert ".png" not in extensions

    def test_scan_skips_git_dir(self, tmp_path):
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        (git_dir / "config.txt").write_text("git stuff", encoding="utf-8")
        (tmp_path / "chat.txt").write_text("hello", encoding="utf-8")
        files = scan_convos(str(tmp_path))
        assert len(files) == 1

    def test_scan_skips_meta_json(self, tmp_path):
        (tmp_path / "chat.meta.json").write_text("{}", encoding="utf-8")
        (tmp_path / "chat.json").write_text("{}", encoding="utf-8")
        files = scan_convos(str(tmp_path))
        names = [f.name for f in files]
        assert "chat.json" in names
        assert "chat.meta.json" not in names

    def test_scan_empty_dir(self, tmp_path):
        files = scan_convos(str(tmp_path))
        assert files == []

    def test_scan_skips_subagent_dirs_by_default(self, tmp_path):
        # Mimic Claude Code layout: ~/.claude/projects/<slug>/<session>/subagents/agent-*.jsonl
        session_dir = tmp_path / "session-abc"
        session_dir.mkdir()
        (session_dir / "main.jsonl").write_text('{"type":"user"}\n', encoding="utf-8")
        subagents_dir = session_dir / "subagents"
        subagents_dir.mkdir()
        (subagents_dir / "agent-abc.jsonl").write_text('{"type":"user"}\n', encoding="utf-8")
        (subagents_dir / "agent-def.jsonl").write_text('{"type":"user"}\n', encoding="utf-8")

        files = scan_convos(str(tmp_path))
        names = [f.name for f in files]

        assert "main.jsonl" in names
        assert "agent-abc.jsonl" not in names
        assert "agent-def.jsonl" not in names

    def test_scan_includes_subagent_dirs_when_opted_in(self, tmp_path):
        session_dir = tmp_path / "session-abc"
        session_dir.mkdir()
        (session_dir / "main.jsonl").write_text('{"type":"user"}\n', encoding="utf-8")
        subagents_dir = session_dir / "subagents"
        subagents_dir.mkdir()
        (subagents_dir / "agent-abc.jsonl").write_text('{"type":"user"}\n', encoding="utf-8")

        files = scan_convos(str(tmp_path), include_subagents=True)
        names = [f.name for f in files]

        assert "main.jsonl" in names
        assert "agent-abc.jsonl" in names

    def test_scan_skips_subagent_dirs_at_any_depth(self, tmp_path):
        # The "subagents" name match is by directory name, not by depth — verify
        # both shallow (top-level) and nested subagents/ get skipped.
        (tmp_path / "subagents").mkdir()
        (tmp_path / "subagents" / "agent-top.jsonl").write_text("{}", encoding="utf-8")
        nested = tmp_path / "session" / "subagents"
        nested.mkdir(parents=True)
        (nested / "agent-deep.jsonl").write_text("{}", encoding="utf-8")
        (tmp_path / "session" / "main.jsonl").write_text("{}", encoding="utf-8")

        files = scan_convos(str(tmp_path))
        names = [f.name for f in files]

        assert "main.jsonl" in names
        assert "agent-top.jsonl" not in names
        assert "agent-deep.jsonl" not in names


class TestFileChunksLocked:
    def test_uses_bounded_upsert_batches(self, monkeypatch):
        import mempalace.convo_miner as convo_miner

        class FakeCol:
            def __init__(self):
                self.batch_sizes = []

            def delete(self, *args, **kwargs):
                pass

            def upsert(self, documents, ids, metadatas):
                self.batch_sizes.append(len(documents))

        chunks = [{"content": f"chunk {i} " * 20, "chunk_index": i} for i in range(5)]
        col = FakeCol()
        monkeypatch.setattr(convo_miner, "DRAWER_UPSERT_BATCH_SIZE", 2)
        monkeypatch.setattr(
            convo_miner, "file_already_mined", lambda collection, source_file: False
        )
        monkeypatch.setattr(convo_miner, "mine_lock", lambda source_file: contextlib.nullcontext())
        monkeypatch.setattr(convo_miner, "_detect_hall_cached", lambda content: "conversations")

        drawers, room_counts, skipped = _file_chunks_locked(
            col, "chat.txt", chunks, "wing", "general", "agent", "exchange"
        )

        assert drawers == 5
        assert dict(room_counts) == {}
        assert skipped is False
        assert col.batch_sizes == [2, 2, 1]
