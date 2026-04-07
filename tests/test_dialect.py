"""
Tests for dialect.py — AAAK Dialect Compressed Symbolic Memory Language.

Covers:
  - Plain text compression to AAAK format
  - Metadata-enriched compression (wing, room, source)
  - Entity encoding (known mappings, auto-code fallback, skip names)
  - Emotion encoding and keyword-based detection
  - Flag detection from text keywords
  - Topic extraction with stop word filtering
  - Key sentence extraction and scoring
  - Token counting and compression statistics
  - AAAK decoding back to structured dict
  - Config file persistence (from_config / save_config)
"""

import os
import json
import tempfile
import shutil

from mempalace.dialect import Dialect


# ── Plain text compression ────────────────────────────────────────────


def test_compress_plain_text():
    """Compressing plain text produces AAAK format with pipe-delimited fields."""
    dialect = Dialect()
    text = "We decided to use GraphQL instead of REST because of the flexibility."
    compressed = dialect.compress(text)

    assert "|" in compressed
    assert len(compressed) > 0
    # Should contain a zettel-like line with entity:topics
    assert ":" in compressed


def test_compress_with_metadata():
    """Compression with metadata includes a header line with wing/room/date/source."""
    dialect = Dialect()
    text = "Kai recommended Clerk over Auth0 for the auth migration."
    metadata = {
        "wing": "wing_driftwood",
        "room": "auth-migration",
        "date": "2026-01-15",
        "source_file": "/chats/session_42.txt",
    }
    compressed = dialect.compress(text, metadata=metadata)

    lines = compressed.strip().split("\n")
    assert len(lines) >= 2  # header + content
    header = lines[0]
    assert "wing_driftwood" in header
    assert "auth-migration" in header
    assert "2026-01-15" in header


def test_compress_produces_shorter_output():
    """AAAK compression should produce output shorter than the original text."""
    dialect = Dialect()
    text = (
        "Priya manages the Driftwood team: Kai handles backend with 3 years of experience, "
        "Soren works on frontend, Maya runs infrastructure, and Leo is the junior developer "
        "who started last month. They are building a SaaS analytics platform. The current "
        "sprint focuses on auth migration to Clerk. Kai recommended Clerk over Auth0 based "
        "on pricing and developer experience."
    )
    compressed = dialect.compress(text)

    assert len(compressed) < len(text)


def test_compress_without_metadata_no_header():
    """Compression without metadata should not produce a header line."""
    dialect = Dialect()
    text = "A simple note about database configuration."
    compressed = dialect.compress(text)

    lines = compressed.strip().split("\n")
    # Without metadata, should be a single content line (no header)
    assert len(lines) == 1


# ── Entity encoding ──────────────────────────────────────────────────


def test_encode_entity_known_mapping():
    """Known entity names are mapped to their configured short codes."""
    dialect = Dialect(entities={"Alice": "ALC", "Bob": "BOB"})

    assert dialect.encode_entity("Alice") == "ALC"
    assert dialect.encode_entity("Bob") == "BOB"


def test_encode_entity_case_insensitive():
    """Entity lookup is case-insensitive."""
    dialect = Dialect(entities={"Alice": "ALC"})

    assert dialect.encode_entity("alice") == "ALC"


def test_encode_entity_auto_code():
    """Unknown entities get auto-coded as first 3 chars uppercase."""
    dialect = Dialect()

    result = dialect.encode_entity("Charlie")
    assert result == "CHA"


def test_encode_entity_skip_names():
    """Skip-listed names return None."""
    dialect = Dialect(entities={"Gandalf": "GND"}, skip_names=["Gandalf"])

    result = dialect.encode_entity("Gandalf")
    assert result is None


def test_encode_entity_partial_match():
    """Partial name match within entity codes still resolves."""
    dialect = Dialect(entities={"Alice Smith": "ALS"})

    result = dialect.encode_entity("Alice Smith's project")
    assert result == "ALS"


# ── Emotion encoding ─────────────────────────────────────────────────


def test_encode_emotions_mapping():
    """Emotion names are mapped to their short codes."""
    dialect = Dialect()

    result = dialect.encode_emotions(["vulnerability", "joy", "fear"])
    codes = result.split("+")
    assert "vul" in codes
    assert "joy" in codes
    assert "fear" in codes


def test_encode_emotions_max_three():
    """At most 3 emotions are included in the encoded string."""
    dialect = Dialect()

    result = dialect.encode_emotions(["joy", "fear", "trust", "grief", "wonder"])
    codes = result.split("+")
    assert len(codes) == 3


def test_encode_emotions_deduplication():
    """Duplicate emotions are removed from the encoded string."""
    dialect = Dialect()

    result = dialect.encode_emotions(["joy", "joy", "fear"])
    codes = result.split("+")
    assert codes.count("joy") == 1


# ── Emotion detection from text ───────────────────────────────────────


def test_detect_emotions_from_keywords():
    """Emotion keywords in text are detected and mapped to codes."""
    dialect = Dialect()

    emotions = dialect._detect_emotions("I was really excited about the breakthrough")
    assert "excite" in emotions


def test_detect_emotions_multiple():
    """Multiple emotion keywords produce multiple codes."""
    dialect = Dialect()

    emotions = dialect._detect_emotions("I was worried but also excited and grateful")
    assert len(emotions) >= 2


def test_detect_emotions_empty_text():
    """Text with no emotion keywords returns empty list."""
    dialect = Dialect()

    emotions = dialect._detect_emotions("SELECT * FROM users WHERE id = 1")
    assert emotions == []


# ── Flag detection ────────────────────────────────────────────────────


def test_detect_flags_decision():
    """'decided' keyword triggers DECISION flag."""
    dialect = Dialect()

    flags = dialect._detect_flags("We decided to use PostgreSQL instead of MySQL")
    assert "DECISION" in flags


def test_detect_flags_origin():
    """'created' keyword triggers ORIGIN flag."""
    dialect = Dialect()

    flags = dialect._detect_flags("She created the first version of the tool")
    assert "ORIGIN" in flags


def test_detect_flags_technical():
    """Technical keywords trigger TECHNICAL flag."""
    dialect = Dialect()

    flags = dialect._detect_flags("The database architecture needs a migration")
    assert "TECHNICAL" in flags


def test_detect_flags_max_three():
    """At most 3 flags are returned."""
    dialect = Dialect()

    flags = dialect._detect_flags(
        "She decided to create a new database architecture with the API server"
    )
    assert len(flags) <= 3


# ── Topic extraction ──────────────────────────────────────────────────


def test_extract_topics_filters_stop_words():
    """Common stop words are filtered out of extracted topics."""
    dialect = Dialect()

    topics = dialect._extract_topics("The authentication migration was completed successfully")
    topic_words = [t.lower() for t in topics]
    assert "the" not in topic_words
    assert "was" not in topic_words
    # Meaningful words should remain
    assert any("authenticat" in t or "migrat" in t for t in topic_words)


def test_extract_topics_max_count():
    """Topic extraction respects max_topics parameter."""
    dialect = Dialect()

    topics = dialect._extract_topics(
        "GraphQL PostgreSQL Kubernetes Docker React TypeScript Node Redis",
        max_topics=3,
    )
    assert len(topics) <= 3


# ── Key sentence extraction ───────────────────────────────────────────


def test_extract_key_sentence_prefers_decisions():
    """Key sentence extraction favors sentences with decision keywords."""
    dialect = Dialect()

    text = (
        "The team had a meeting on Monday. "
        "We decided to switch from REST to GraphQL because of flexibility. "
        "The weather was nice outside."
    )
    sentence = dialect._extract_key_sentence(text)

    assert "decided" in sentence.lower() or "graphql" in sentence.lower()


def test_extract_key_sentence_truncates_long():
    """Very long sentences are truncated to ~55 chars."""
    dialect = Dialect()

    text = (
        "This is a very long sentence that goes on and on and on "
        "about many different topics including architecture and design "
        "and it should definitely be truncated by the extraction logic."
    )
    sentence = dialect._extract_key_sentence(text)

    assert len(sentence) <= 60  # 55 + small buffer for "..."


def test_extract_key_sentence_empty_text():
    """Empty or very short text returns empty string."""
    dialect = Dialect()

    sentence = dialect._extract_key_sentence("")
    assert sentence == ""


# ── Token counting and compression stats ──────────────────────────────


def test_count_tokens():
    """Token count uses ~3 chars per token for structured text."""
    result = Dialect.count_tokens("abcdefghi")  # 9 chars
    assert result == 3  # 9 // 3


def test_compression_stats():
    """Compression stats correctly calculates ratio, tokens, and chars."""
    dialect = Dialect()

    original = "This is a test sentence with some content for compression statistics."
    compressed = dialect.compress(original)
    stats = dialect.compression_stats(original, compressed)

    assert stats["original_chars"] == len(original)
    assert stats["compressed_chars"] == len(compressed)
    assert stats["original_tokens"] == len(original) // 3
    assert stats["compressed_tokens"] == len(compressed) // 3
    assert stats["ratio"] > 0
    assert stats["ratio"] == stats["original_tokens"] / max(stats["compressed_tokens"], 1)


# ── Decoding ──────────────────────────────────────────────────────────


def test_decode_aaak_header():
    """Decoding an AAAK string parses the header line correctly."""
    dialect = Dialect()

    aaak_text = '001|ALC+BOB|2025-06-15|team_meeting\n01:ALC|auth_migration|"switched to Clerk"|0.9|excite|DECISION'
    result = dialect.decode(aaak_text)

    assert result["header"]["file"] == "001"
    assert result["header"]["entities"] == "ALC+BOB"
    assert result["header"]["date"] == "2025-06-15"
    assert len(result["zettels"]) == 1


def test_decode_aaak_tunnels():
    """Decoding recognizes tunnel lines starting with 'T:'."""
    dialect = Dialect()

    aaak_text = "001|ALC|2025-06|test\nT:01<->02|auth_connection"
    result = dialect.decode(aaak_text)

    assert len(result["tunnels"]) == 1
    assert "T:" in result["tunnels"][0]


def test_decode_aaak_arc():
    """Decoding recognizes emotional arc lines starting with 'ARC:'."""
    dialect = Dialect()

    aaak_text = "001|ALC|2025-06|test\nARC:hope->fear->relief"
    result = dialect.decode(aaak_text)

    assert result["arc"] == "hope->fear->relief"


# ── Config persistence ────────────────────────────────────────────────


def test_from_config_and_save():
    """Dialect saves config to file and loads it back correctly."""
    tmpdir = tempfile.mkdtemp()
    try:
        config_path = os.path.join(tmpdir, "entities.json")

        # Create and save
        dialect = Dialect(entities={"Alice": "ALC", "Bob": "BOB"}, skip_names=["Gandalf"])
        dialect.save_config(config_path)

        assert os.path.exists(config_path)

        # Load back
        loaded = Dialect.from_config(config_path)
        assert loaded.encode_entity("Alice") == "ALC"
        assert loaded.encode_entity("Bob") == "BOB"
        assert loaded.encode_entity("Gandalf") is None
    finally:
        shutil.rmtree(tmpdir)


def test_save_config_format():
    """Saved config file is valid JSON with expected structure."""
    tmpdir = tempfile.mkdtemp()
    try:
        config_path = os.path.join(tmpdir, "entities.json")
        dialect = Dialect(entities={"Alice": "ALC"})
        dialect.save_config(config_path)

        with open(config_path) as f:
            data = json.load(f)

        assert "entities" in data
        assert "skip_names" in data
        assert isinstance(data["entities"], dict)
        assert isinstance(data["skip_names"], list)
    finally:
        shutil.rmtree(tmpdir)
