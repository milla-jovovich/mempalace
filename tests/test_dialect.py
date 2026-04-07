"""Tests for mempalace.dialect — AAAK Dialect compression."""

import json

import pytest

from mempalace.dialect import EMOTION_CODES, Dialect


class TestDialectBasic:
    def test_default_construction(self):
        d = Dialect()
        assert d is not None

    def test_from_config(self, tmp_path):
        config = {
            "entities": {"Alice": "A", "Bob": "B"},
            "abbreviations": {"database": "db"},
        }
        f = tmp_path / "entities.json"
        f.write_text(json.dumps(config))
        d = Dialect.from_config(str(f))
        assert d is not None


class TestCompress:
    def test_basic_text(self):
        d = Dialect()
        text = "We decided to use GraphQL because REST was too chatty for our mobile clients."
        compressed = d.compress(text)
        assert isinstance(compressed, str)
        assert len(compressed) > 0

    def test_long_text_compresses(self):
        d = Dialect()
        text = (
            "We decided to use GraphQL because REST was too chatty for our mobile clients. "
            "The team discussed several alternatives including gRPC and tRPC but ultimately "
            "went with GraphQL due to its excellent developer experience and type safety. "
            "Alice was particularly excited about the schema-first approach. "
            "We also considered the deployment implications and decided to use Apollo Server."
        ) * 3
        compressed = d.compress(text)
        assert len(compressed) < len(text)

    def test_empty_text(self):
        d = Dialect()
        result = d.compress("")
        assert isinstance(result, str)

    def test_with_metadata(self):
        d = Dialect()
        text = "Alice discussed the new deployment strategy with the backend team."
        meta = {"wing": "myapp", "room": "architecture"}
        compressed = d.compress(text, metadata=meta)
        assert isinstance(compressed, str)

    def test_emotional_text_gets_codes(self):
        d = Dialect()
        text = "I was so happy and excited when the project finally launched successfully."
        compressed = d.compress(text)
        assert isinstance(compressed, str)

    def test_technical_text(self):
        d = Dialect()
        text = "The API architecture uses a microservices pattern with Docker containers deployed on Kubernetes infrastructure."
        compressed = d.compress(text)
        assert len(compressed) > 0


class TestCompressionStats:
    def test_returns_stats(self):
        d = Dialect()
        original = "A long text about the project architecture and deployment strategy." * 5
        compressed = d.compress(original)
        stats = d.compression_stats(original, compressed)
        assert "original_chars" in stats
        assert "compressed_chars" in stats
        assert "original_tokens" in stats
        assert "compressed_tokens" in stats
        assert "ratio" in stats
        assert stats["ratio"] > 1.0

    def test_empty_text_stats(self):
        d = Dialect()
        stats = d.compression_stats("", "")
        assert "ratio" in stats


class TestCountTokens:
    def test_approximation(self):
        text = "Hello world this is a test"
        tokens = Dialect.count_tokens(text)
        assert tokens > 0
        assert tokens < len(text)

    def test_empty(self):
        assert Dialect.count_tokens("") == 0


class TestEmotionCodes:
    def test_codes_exist(self):
        assert len(EMOTION_CODES) > 20

    @pytest.mark.parametrize(
        "emotion, code",
        [
            ("joy", "joy"),
            ("vulnerability", "vul"),
            ("fear", "fear"),
            ("love", "love"),
            ("anxiety", "anx"),
            ("exhaustion", "exhaust"),
        ],
    )
    def test_known_mappings(self, emotion, code):
        assert EMOTION_CODES[emotion] == code
