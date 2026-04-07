"""Tests for mempalace.general_extractor — 5 memory type extraction."""

import pytest

from mempalace.general_extractor import (
    _disambiguate,
    _extract_prose,
    _get_sentiment,
    _has_resolution,
    _is_code_line,
    _score_markers,
    _split_into_segments,
    DECISION_MARKERS,
    EMOTION_MARKERS,
    MILESTONE_MARKERS,
    PREFERENCE_MARKERS,
    PROBLEM_MARKERS,
    extract_memories,
)


class TestScoreMarkers:
    def test_decision_markers(self):
        score, kws = _score_markers("We decided to use GraphQL because REST was slow", DECISION_MARKERS)
        assert score > 0

    def test_preference_markers(self):
        score, _ = _score_markers("I prefer to always use functional style", PREFERENCE_MARKERS)
        assert score > 0

    def test_milestone_markers(self):
        score, _ = _score_markers("It finally works! Got it working after 3 days.", MILESTONE_MARKERS)
        assert score > 0

    def test_problem_markers(self):
        score, _ = _score_markers("Bug in the auth module, error keeps crashing", PROBLEM_MARKERS)
        assert score > 0

    def test_emotion_markers(self):
        score, _ = _score_markers("I feel so happy and proud of what we built", EMOTION_MARKERS)
        assert score > 0

    def test_no_markers(self):
        score, kws = _score_markers("The quick brown fox jumps over the lazy dog", DECISION_MARKERS)
        assert score == 0


class TestGetSentiment:
    def test_positive(self):
        assert _get_sentiment("This is amazing and wonderful, I'm so proud!") == "positive"

    def test_negative(self):
        assert _get_sentiment("Everything is broken, the bug crashed and failed") == "negative"

    def test_neutral(self):
        assert _get_sentiment("The quick brown fox jumps over the lazy dog") == "neutral"


class TestHasResolution:
    def test_fixed(self):
        assert _has_resolution("Finally fixed the auth token bug") is True

    def test_solved(self):
        assert _has_resolution("Solved the deployment issue") is True

    def test_no_resolution(self):
        assert _has_resolution("The bug keeps crashing") is False


class TestDisambiguate:
    def test_resolved_problem_becomes_milestone(self):
        result = _disambiguate("problem", "The bug was broken but finally fixed it", {"milestone": 2})
        assert result == "milestone"

    def test_positive_problem_becomes_milestone(self):
        result = _disambiguate("problem", "amazing success works perfectly", {"milestone": 1, "emotional": 0})
        assert result == "milestone"

    def test_unresolved_stays_problem(self):
        result = _disambiguate("problem", "broken and crashing badly", {})
        assert result == "problem"


class TestIsCodeLine:
    @pytest.mark.parametrize(
        "line",
        [
            "  $ npm install",
            "  import os",
            "  from pathlib import Path",
            "  def main():",
            "  git commit -m 'fix'",
            "  ```python",
            "  API_KEY=abc123",
        ],
    )
    def test_code_lines(self, line):
        assert _is_code_line(line) is True

    @pytest.mark.parametrize(
        "line",
        [
            "We decided to use GraphQL",
            "The project is going well",
            "Alice loves chess",
            "",
        ],
    )
    def test_prose_lines(self, line):
        assert _is_code_line(line) is False


class TestExtractProse:
    def test_strips_code_blocks(self):
        text = "Real content here.\n```python\nimport os\n```\nMore real content."
        prose = _extract_prose(text)
        assert "import os" not in prose
        assert "Real content" in prose

    def test_strips_inline_code(self):
        text = "Good prose.\n  $ pip install foo\nMore prose."
        prose = _extract_prose(text)
        assert "pip install" not in prose


class TestSplitIntoSegments:
    def test_speaker_turns(self):
        text = "> Question one\nAnswer one\n\n> Question two\nAnswer two\n\n> Question three\nAnswer three"
        segments = _split_into_segments(text)
        assert len(segments) >= 2

    def test_paragraph_split(self):
        text = "First paragraph about decisions.\n\nSecond paragraph about problems."
        segments = _split_into_segments(text)
        assert len(segments) == 2

    def test_long_single_block(self):
        text = "\n".join(f"Line {i} with content." for i in range(30))
        segments = _split_into_segments(text)
        assert len(segments) >= 1


class TestExtractMemories:
    def test_decision_extraction(self):
        text = "We decided to switch to GraphQL because REST was too chatty. The trade-off was worth it for our mobile clients."
        memories = extract_memories(text, min_confidence=0.1)
        types = [m["memory_type"] for m in memories]
        assert "decision" in types

    def test_preference_extraction(self):
        text = "I prefer to always use functional style. Never use mutable state. My rule is immutability everywhere."
        memories = extract_memories(text, min_confidence=0.1)
        types = [m["memory_type"] for m in memories]
        assert "preference" in types

    def test_milestone_extraction(self):
        text = "It finally works! After three days of debugging, got it working. Deployed version 2.0 successfully."
        memories = extract_memories(text, min_confidence=0.1)
        types = [m["memory_type"] for m in memories]
        assert "milestone" in types

    def test_problem_extraction(self):
        text = "Bug in the auth module: the token keeps failing and crashing. The error happens on every request."
        memories = extract_memories(text, min_confidence=0.1)
        types = [m["memory_type"] for m in memories]
        assert "problem" in types

    def test_emotional_extraction(self):
        text = "I feel so proud of what we built. It's beautiful and amazing. I love this project."
        memories = extract_memories(text, min_confidence=0.1)
        types = [m["memory_type"] for m in memories]
        assert "emotional" in types

    def test_empty_text(self):
        assert extract_memories("") == []

    def test_short_text_filtered(self):
        assert extract_memories("hi") == []

    def test_chunk_index_sequential(self):
        text = (
            "We decided to use X because Y. The trade-off was good.\n\n"
            "Bug in module Z. The error keeps crashing.\n\n"
            "Finally fixed it! It works now. Deployed v3.0.\n\n"
        )
        memories = extract_memories(text, min_confidence=0.1)
        indices = [m["chunk_index"] for m in memories]
        assert indices == list(range(len(indices)))

    def test_min_confidence_filter(self):
        text = "Some vague text about things and stuff that might barely match."
        high = extract_memories(text, min_confidence=0.9)
        low = extract_memories(text, min_confidence=0.1)
        assert len(high) <= len(low)
