import chromadb
import pytest
from mempalace.convo_miner import (
    mine_convos,
    chunk_exchanges,
    detect_convo_room,
    scan_convos,
    _chunk_by_paragraph,
    _chunk_by_exchange,
)


def test_convo_mining(tmp_dir, palace_path):
    chat = tmp_dir / "chat.txt"
    chat.write_text(
        "> What is memory?\nMemory is persistence.\n\n"
        "> Why does it matter?\nIt enables continuity.\n\n"
        "> How do we build it?\nWith structured storage.\n"
    )

    mine_convos(str(tmp_dir), palace_path, wing="test_convos")

    client = chromadb.PersistentClient(path=palace_path)
    col = client.get_collection("mempalace_drawers")
    assert col.count() == 3  # 3 exchange pairs


def test_chunk_exchanges_with_markers():
    content = (
        "> Question one?\nAnswer one is here.\n\n"
        "> Question two?\nAnswer two is here.\n\n"
        "> Question three?\nAnswer three is here.\n"
    )
    chunks = chunk_exchanges(content)
    assert len(chunks) == 3
    assert "> Question one?" in chunks[0]["content"]
    assert "Answer one is here." in chunks[0]["content"]


def test_chunk_exchanges_falls_back_to_paragraphs():
    content = "First paragraph about something.\n\nSecond paragraph about another thing entirely.\n"
    chunks = chunk_exchanges(content)
    assert len(chunks) == 2


def test_detect_convo_room_technical():
    assert detect_convo_room("We found a bug in the python api server") == "technical"


def test_detect_convo_room_decisions():
    assert detect_convo_room("We decided to switch and migrated the approach") == "decisions"


def test_detect_convo_room_general():
    assert detect_convo_room("Hello how are you today") == "general"


def test_mine_convos_skips_already_filed(tmp_dir, palace_path):
    chat = tmp_dir / "chat.txt"
    chat.write_text("> First question?\nFirst answer.\n\n> Second question?\nSecond answer.\n")
    mine_convos(str(tmp_dir), palace_path, wing="test")
    client = chromadb.PersistentClient(path=palace_path)
    col = client.get_collection("mempalace_drawers")
    count_after_first = col.count()

    # Mine again — should skip
    mine_convos(str(tmp_dir), palace_path, wing="test")
    assert col.count() == count_after_first


# ---------------------------------------------------------------------------
# New tests
# ---------------------------------------------------------------------------


def test_chunk_by_paragraph_line_group_fallback():
    """Content with >20 lines but no double-newline breaks uses 25-line groups."""
    # Build 30 distinct lines with no paragraph breaks (no double newlines)
    lines = [f"This is line number {i} with enough text to matter." for i in range(30)]
    content = "\n".join(lines)

    # Sanity-check: no paragraph breaks in the content
    assert "\n\n" not in content

    chunks = _chunk_by_paragraph(content)

    # 30 lines split into groups of 25 => 2 chunks (25 + 5)
    assert len(chunks) == 2
    # First chunk should contain the first line
    assert "line number 0" in chunks[0]["content"]
    # Second chunk should start from line 25
    assert "line number 25" in chunks[1]["content"]
    # chunk_index values are sequential
    assert chunks[0]["chunk_index"] == 0
    assert chunks[1]["chunk_index"] == 1


def test_chunk_by_exchange_ai_response_truncated_at_8_lines():
    """An AI response longer than 8 lines is truncated to the first 8 lines."""
    # Build a single exchange: one user turn followed by 12 AI response lines
    ai_lines = [f"AI response line {i} with sufficient text here." for i in range(12)]
    content_lines = ["> User question that is long enough to pass the min chunk check."] + ai_lines
    chunks = _chunk_by_exchange(content_lines)

    assert len(chunks) == 1
    chunk_text = chunks[0]["content"]

    # The first 8 AI lines must be present (joined by spaces)
    for i in range(8):
        assert f"AI response line {i}" in chunk_text

    # Lines 8-11 must NOT be included
    for i in range(8, 12):
        assert f"AI response line {i}" not in chunk_text


def test_mine_convos_general_mode_uses_memory_type_rooms(tmp_dir, palace_path):
    """mine_convos with extract_mode='general' stores chunks with memory_type-based rooms."""
    chat = tmp_dir / "decisions.txt"
    # Write content that general_extractor will classify as a decision
    chat.write_text(
        "We decided to go with PostgreSQL instead of MySQL because of better JSON support "
        "and the trade-off was worth it given our architecture requirements. "
        "We chose this approach after evaluating alternatives and the strategy was clear."
    )

    mine_convos(str(tmp_dir), palace_path, wing="gen_test", extract_mode="general")

    client = chromadb.PersistentClient(path=palace_path)
    col = client.get_collection("mempalace_drawers")

    # At least one chunk should have been filed
    assert col.count() >= 1

    # Every filed chunk should use a memory_type as its room (not "general" topic detection)
    valid_memory_types = {"decision", "preference", "milestone", "problem", "emotional"}
    results = col.get(include=["metadatas"])
    for meta in results["metadatas"]:
        assert meta["extract_mode"] == "general"
        assert meta["room"] in valid_memory_types


def test_scan_convos_skips_meta_json_files(tmp_dir):
    """scan_convos must exclude any file ending with .meta.json."""
    # Create a regular conversation file and a .meta.json sidecar
    (tmp_dir / "chat.txt").write_text("Some conversation content here.")
    (tmp_dir / "chat.meta.json").write_text('{"source": "claude"}')
    (tmp_dir / "notes.md").write_text("More conversation notes here.")
    (tmp_dir / "export.meta.json").write_text('{"exported_at": "2026-01-01"}')

    found = scan_convos(str(tmp_dir))
    found_names = [f.name for f in found]

    # Regular files should be included
    assert "chat.txt" in found_names
    assert "notes.md" in found_names

    # .meta.json files must be excluded
    assert "chat.meta.json" not in found_names
    assert "export.meta.json" not in found_names
