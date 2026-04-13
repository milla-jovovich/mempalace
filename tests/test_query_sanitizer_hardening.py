"""Additional invariants for query sanitizer edge cases."""

import pytest

from mempalace.query_sanitizer import MAX_QUERY_LENGTH, sanitize_query


@pytest.mark.parametrize(
    "query",
    [
        ('System prompt. ' * 40) + 'What happened to auth migration?"',
        ('Status dump. ' * 40) + "Why did we switch databases?'",
    ],
)
def test_question_extraction_accepts_trailing_quotes(query):
    result = sanitize_query(query)

    assert result["was_sanitized"] is True
    assert result["method"] == "question_extraction"
    assert "auth migration" in result["clean_query"] or "switch databases" in result["clean_query"]


@pytest.mark.parametrize(
    ("query", "expected_tail"),
    [
        (("Header line\n" * 120) + "auth migration rollback plan", "auth migration rollback plan"),
        (("Metadata block. " * 80) + "\nvector search migration notes", "vector search migration notes"),
        (("x\n" * 300) + "final meaningful tail segment", "final meaningful tail segment"),
    ],
)
def test_sanitize_query_keeps_tail_focus_for_long_non_question_queries(query, expected_tail):
    result = sanitize_query(query)

    assert result["was_sanitized"] is True
    assert len(result["clean_query"]) <= MAX_QUERY_LENGTH
    assert expected_tail in result["clean_query"]


def test_sanitize_query_prefers_last_question_even_after_earlier_questions():
    query = (
        ("Old question? " * 20)
        + "Context dump that should not win. "
        + "What was the final decision on passkeys?"
    )

    result = sanitize_query(query)

    assert result["method"] == "question_extraction"
    assert "final decision on passkeys" in result["clean_query"]


def test_sanitize_query_never_returns_blank_for_long_nonblank_input():
    query = ("meta\n" * 250) + "actual search tail"

    result = sanitize_query(query)

    assert result["was_sanitized"] is True
    assert result["clean_query"].strip()
