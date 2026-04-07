from mempalace.dialect import Dialect


def test_encode_entity_known():
    d = Dialect(entities={"Alice": "ALC", "Bob": "BOB"})
    assert d.encode_entity("Alice") == "ALC"
    assert d.encode_entity("alice") == "ALC"  # case insensitive


def test_encode_entity_unknown():
    d = Dialect()
    assert d.encode_entity("Zara") == "ZAR"  # auto-code: first 3 upper


def test_encode_entity_skip():
    d = Dialect(skip_names=["Gandalf"])
    assert d.encode_entity("Gandalf") is None


def test_encode_emotions():
    d = Dialect()
    result = d.encode_emotions(["joy", "grief", "vulnerability"])
    assert result == "joy+grief+vul"


def test_encode_emotions_max_three():
    d = Dialect()
    result = d.encode_emotions(["joy", "grief", "fear", "love"])
    assert result.count("+") == 2  # max 3 items = 2 pluses


def test_encode_emotions_unknown():
    d = Dialect()
    result = d.encode_emotions(["xylophone"])
    assert result == "xylo"  # truncated to 4 chars


def test_compress_basic():
    d = Dialect(entities={"Alice": "ALC"})
    text = "Alice decided to use GraphQL instead of REST because it reduces overfetching."
    compressed = d.compress(text)
    assert "ALC" in compressed
    assert "|" in compressed  # pipe-separated fields


def test_compress_with_metadata():
    d = Dialect()
    text = "We decided to switch the database."
    compressed = d.compress(
        text, metadata={"wing": "code", "room": "backend", "date": "2026-03-01"}
    )
    assert "code" in compressed
    assert "backend" in compressed


def test_detect_emotions():
    d = Dialect()
    emotions = d._detect_emotions("I was excited but also worried about the deadline")
    assert "excite" in emotions
    assert "anx" in emotions


def test_detect_flags():
    d = Dialect()
    flags = d._detect_flags("We decided to migrate the database architecture")
    assert "DECISION" in flags
    assert "TECHNICAL" in flags


def test_extract_topics():
    d = Dialect()
    topics = d._extract_topics("The chromadb vector database stores embeddings for semantic search")
    assert len(topics) > 0
    assert any("chromadb" in t or "vector" in t or "database" in t for t in topics)


def test_decode_round_trip():
    d = Dialect(entities={"Alice": "ALC"})
    text = "Alice discovered a breakthrough in the database architecture"
    compressed = d.compress(text, metadata={"wing": "code", "room": "backend"})
    decoded = d.decode(compressed)
    assert "header" in decoded
    assert "zettels" in decoded


def test_compression_stats():
    d = Dialect()
    original = (
        "We decided to switch from REST to GraphQL because it reduces overfetching and allows "
        "the client to request exactly the fields it needs. This dramatically improves performance "
        "for mobile users with limited bandwidth. The database architecture was also updated to "
        "support the new query patterns more efficiently across all services."
    )
    assert len(original) >= 300
    compressed = d.compress(original)
    stats = d.compression_stats(original, compressed)
    assert stats["original_chars"] == len(original)
    assert stats["summary_chars"] < len(original)
    assert stats["size_ratio"] > 1.0


def test_from_config_and_save(tmp_dir):
    config_path = str(tmp_dir / "entities.json")
    original = Dialect(entities={"Alice": "ALC", "Bob": "BOB"})
    original.save_config(config_path)

    loaded = Dialect.from_config(config_path)
    assert loaded.encode_entity("Alice") == "ALC"
    assert loaded.encode_entity("Bob") == "BOB"


def test_encode_zettel_format():
    d = Dialect(entities={"Alice": "ALC", "Bob": "BOB"})
    zettel = {
        "id": "file_001-z003",
        "people": ["Alice", "Bob"],
        "topics": ["graphql", "backend"],
        "emotional_weight": 0.8,
        "emotional_tone": ["joy", "trust"],
    }
    result = d.encode_zettel(zettel)
    # Should be pipe-separated fields
    assert "|" in result
    parts = result.split("|")
    # First field: ZID:ENTITIES (last segment of id : entity codes)
    assert parts[0].startswith("z003:")
    # Entity codes should appear in the first field
    assert "ALC" in parts[0] and "BOB" in parts[0]
    # Topics joined with underscore
    assert "graphql_backend" in result
    # Weight should appear as a field
    assert "0.8" in result
    # Emotions should be encoded
    assert "joy" in result


def test_encode_zettel_pipe_count():
    d = Dialect()
    zettel = {
        "id": "file_001-z001",
        "people": [],
        "topics": ["testing"],
        "emotional_weight": 0.5,
        "emotional_tone": [],
    }
    result = d.encode_zettel(zettel)
    # Minimum fields: ZID:ENTITIES | topic | weight  → at least 2 pipes
    assert result.count("|") >= 2


def test_encode_file_header_and_zettels():
    d = Dialect(entities={"Alice": "ALC"})
    zettel_file = {
        "source_file": "001-alice-chat.txt",
        "zettels": [
            {
                "id": "001-z001",
                "date_context": "2026-01-01",
                "people": ["Alice"],
                "topics": ["memory"],
                "emotional_weight": 0.7,
                "emotional_tone": ["hope"],
            },
            {
                "id": "001-z002",
                "date_context": "2026-01-01",
                "people": ["Alice"],
                "topics": ["code"],
                "emotional_weight": 0.6,
                "emotional_tone": [],
            },
        ],
        "tunnels": [],
    }
    result = d.encode_file(zettel_file)
    lines = result.strip().splitlines()
    # First line is the header: file_num|primary_entity|date|title
    header = lines[0]
    assert "|" in header
    header_parts = header.split("|")
    assert header_parts[0] == "001"        # file_num from "001-alice-chat.txt"
    assert "ALC" in header_parts[1]        # primary entity code
    assert header_parts[2] == "2026-01-01" # date from first zettel
    # Remaining lines are zettel encodings
    assert len(lines) >= 3  # header + 2 zettel lines
    # Each zettel line should be pipe-separated
    for line in lines[1:]:
        assert "|" in line


def test_encode_file_with_tunnels():
    d = Dialect()
    zettel_file = {
        "source_file": "002-test.txt",
        "zettels": [
            {
                "id": "002-z001",
                "date_context": "2026-02-01",
                "people": [],
                "topics": ["test"],
                "emotional_weight": 0.5,
                "emotional_tone": [],
            }
        ],
        "tunnels": [
            {"from": "002-z001", "to": "002-z002", "label": "connects:ideas"}
        ],
    }
    result = d.encode_file(zettel_file)
    # Tunnel lines start with "T:"
    assert "T:" in result
    assert "z001<->z002" in result


def test_count_tokens_basic():
    d = Dialect()
    # A 10-word sentence: 10 * 1.3 = 13 tokens
    text = "one two three four five six seven eight nine ten"
    result = d.count_tokens(text)
    assert result == 13


def test_count_tokens_static_method():
    # count_tokens is a @staticmethod — callable without instance
    text = "hello world foo bar"  # 4 words → int(4 * 1.3) = 5
    result = Dialect.count_tokens(text)
    assert result == 5


def test_count_tokens_minimum_one():
    # Empty string edge case — minimum is 1
    result = Dialect.count_tokens("")
    assert result == 1
