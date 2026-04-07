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
    assert stats["compressed_chars"] < len(original)
    assert stats["ratio"] > 1.0


def test_from_config_and_save(tmp_dir):
    config_path = str(tmp_dir / "entities.json")
    original = Dialect(entities={"Alice": "ALC", "Bob": "BOB"})
    original.save_config(config_path)

    loaded = Dialect.from_config(config_path)
    assert loaded.encode_entity("Alice") == "ALC"
    assert loaded.encode_entity("Bob") == "BOB"
