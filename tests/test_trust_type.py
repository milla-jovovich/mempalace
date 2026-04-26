"""Tests for mempalace.trust_type — prefix-based agent classification."""

import pytest

from mempalace.trust_type import (
    TRUST_TYPE_HUMAN,
    TRUST_TYPE_LLM_JUDGE,
    TRUST_TYPE_MECHANICAL,
    parse_trust_type,
)


class TestParseTrustType:
    def test_mechanical_prefix(self):
        assert parse_trust_type("mechanical:memory-harvest") == TRUST_TYPE_MECHANICAL
        assert parse_trust_type("mechanical:dos-rate-hook") == TRUST_TYPE_MECHANICAL
        assert parse_trust_type("mechanical:a") == TRUST_TYPE_MECHANICAL

    def test_human_prefix(self):
        assert parse_trust_type("human:lucas") == TRUST_TYPE_HUMAN
        assert parse_trust_type("human:someone@example.com") == TRUST_TYPE_HUMAN

    def test_llm_judge_prefix(self):
        assert parse_trust_type("llm_judge:claude-opus-4-7") == TRUST_TYPE_LLM_JUDGE
        assert parse_trust_type("llm_judge:gpt-4o") == TRUST_TYPE_LLM_JUDGE

    def test_unrecognized_prefix_returns_none(self):
        # Legacy free-form agent names — no trust_type inferred.
        assert parse_trust_type("mcp") is None
        assert parse_trust_type("memory-harvest") is None
        assert parse_trust_type("dos-rate-hook") is None
        assert parse_trust_type("sentinel") is None

    def test_prefix_without_specifier_returns_none(self):
        # Caller set the prefix but didn't name the agent — reject rather
        # than classify, so malformed writes don't silently inherit a type.
        assert parse_trust_type("mechanical:") is None
        assert parse_trust_type("human:") is None
        assert parse_trust_type("llm_judge:") is None

    def test_similar_but_wrong_prefix(self):
        # Substring match must be anchored to the start and end with ":".
        assert parse_trust_type("mechanicalish:name") is None
        assert parse_trust_type("not-mechanical:name") is None
        assert parse_trust_type("human-ish:name") is None

    def test_empty_and_none(self):
        assert parse_trust_type("") is None
        assert parse_trust_type(None) is None

    def test_non_string_input(self):
        # Defensive: callers sometimes pass through chromadb metadata which
        # could be any JSON-serializable value. Treat non-str as unclassified.
        assert parse_trust_type(123) is None  # type: ignore[arg-type]
        assert parse_trust_type(["mechanical:x"]) is None  # type: ignore[arg-type]

    @pytest.mark.parametrize(
        "added_by,expected",
        [
            ("mechanical:memory-harvest", TRUST_TYPE_MECHANICAL),
            ("human:lucas", TRUST_TYPE_HUMAN),
            ("llm_judge:claude-opus-4-7", TRUST_TYPE_LLM_JUDGE),
            ("mcp", None),
            ("", None),
        ],
    )
    def test_table(self, added_by, expected):
        assert parse_trust_type(added_by) == expected
