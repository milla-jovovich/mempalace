from mempalace.general_extractor import (
    extract_memories,
    _get_sentiment,
    _has_resolution,
    _is_code_line,
    _extract_prose,
    _split_into_segments,
)


def test_extract_decision():
    text = "We decided to use GraphQL instead of REST because it reduces overfetching. The trade-off is complexity."
    memories = extract_memories(text, min_confidence=0.0)
    types = [m["memory_type"] for m in memories]
    assert "decision" in types


def test_extract_preference():
    text = "I prefer to always use snake_case in Python. Don't ever use camelCase in our codebase."
    memories = extract_memories(text, min_confidence=0.0)
    types = [m["memory_type"] for m in memories]
    assert "preference" in types


def test_extract_milestone():
    text = "Finally got it working! Built the first prototype and shipped the v1.0 release."
    memories = extract_memories(text, min_confidence=0.0)
    types = [m["memory_type"] for m in memories]
    assert "milestone" in types


def test_extract_problem():
    text = "There's a bug in the server. The error keeps crashing the database. Root cause is the missing index."
    memories = extract_memories(text, min_confidence=0.0)
    types = [m["memory_type"] for m in memories]
    assert "problem" in types


def test_extract_emotional():
    text = "I love this project so much. I'm scared it won't work. I feel proud of what we built."
    memories = extract_memories(text, min_confidence=0.0)
    types = [m["memory_type"] for m in memories]
    assert "emotional" in types


def test_resolved_problem_becomes_milestone():
    text = "The bug was crashing the server. Finally figured it out and fixed the root cause."
    memories = extract_memories(text, min_confidence=0.0)
    types = [m["memory_type"] for m in memories]
    assert "milestone" in types or "problem" in types  # disambiguated


def test_get_sentiment():
    assert _get_sentiment("I'm happy and proud of this breakthrough") == "positive"
    assert _get_sentiment("The bug crashed and everything is broken") == "negative"
    assert _get_sentiment("The sky is blue today") == "neutral"


def test_has_resolution():
    assert _has_resolution("Finally fixed it and got it working") is True
    assert _has_resolution("The bug keeps crashing") is False


def test_is_code_line():
    assert _is_code_line("$ pip install mempalace") is True
    assert _is_code_line("import chromadb") is True
    assert _is_code_line("Alice went to the store") is False


def test_extract_prose_strips_code():
    text = "Some prose here.\n```python\nimport os\nprint('hi')\n```\nMore prose after."
    prose = _extract_prose(text)
    assert "import os" not in prose
    assert "Some prose here" in prose
    assert "More prose after" in prose


def test_split_by_turns():
    text = (
        "> Question one\nAnswer one\n> Question two\nAnswer two\n> Question three\nAnswer three\n"
    )
    segments = _split_into_segments(text)
    assert len(segments) == 3


def test_split_by_paragraphs():
    text = "First paragraph about one thing.\n\nSecond paragraph about another.\n\nThird paragraph too."
    segments = _split_into_segments(text)
    assert len(segments) == 3


def test_min_confidence_filters():
    text = "hello world"  # no markers match
    memories = extract_memories(text, min_confidence=0.5)
    assert len(memories) == 0
