"""
Tests for sanitize_kg_object and the fix for issue #455.

The KG object field should accept descriptive text with commas, colons,
parentheses, and other common punctuation — unlike sanitize_name which
is restricted to entity-ID-safe characters.
"""

import pytest

from mempalace.config import sanitize_kg_object, sanitize_name, MAX_KG_OBJECT_LENGTH


# ── Basic acceptance: values that MUST be allowed ────────────────────────────


class TestSanitizeKgObjectAccepts:
    """Descriptive text that sanitize_name rejects but sanitize_kg_object must allow."""

    def test_plain_word(self):
        assert sanitize_kg_object("coffee") == "coffee"

    def test_commas(self):
        assert sanitize_kg_object("chess, swimming, reading") == "chess, swimming, reading"

    def test_colons(self):
        assert sanitize_kg_object("role: engineer") == "role: engineer"

    def test_semicolons(self):
        assert sanitize_kg_object("a; b; c") == "a; b; c"

    def test_parentheses(self):
        assert sanitize_kg_object("Alice (daughter)") == "Alice (daughter)"

    def test_square_brackets(self):
        assert sanitize_kg_object("tags [important]") == "tags [important]"

    def test_curly_braces(self):
        assert sanitize_kg_object("config {debug}") == "config {debug}"

    def test_exclamation_mark(self):
        assert sanitize_kg_object("urgent!") == "urgent!"

    def test_question_mark(self):
        assert sanitize_kg_object("unknown?") == "unknown?"

    def test_at_sign(self):
        assert sanitize_kg_object("user@domain") == "user@domain"

    def test_hash(self):
        assert sanitize_kg_object("issue #455") == "issue #455"

    def test_percent(self):
        assert sanitize_kg_object("80% complete") == "80% complete"

    def test_ampersand(self):
        assert sanitize_kg_object("R&D department") == "R&D department"

    def test_plus(self):
        assert sanitize_kg_object("C++ developer") == "C++ developer"

    def test_equals(self):
        assert sanitize_kg_object("x = 42") == "x = 42"

    def test_pipe(self):
        assert sanitize_kg_object("a | b") == "a | b"

    def test_tilde(self):
        assert sanitize_kg_object("~approximate") == "~approximate"

    def test_caret(self):
        assert sanitize_kg_object("version ^2.0") == "version ^2.0"

    def test_dash_and_underscore(self):
        assert sanitize_kg_object("long-term_goal") == "long-term_goal"

    def test_quotes(self):
        assert sanitize_kg_object('"hello world"') == '"hello world"'
        assert sanitize_kg_object("it's fine") == "it's fine"

    def test_mixed_punctuation_sentence(self):
        val = "Born April 1, 2015 (age 11); loves chess, swimming, and reading"
        assert sanitize_kg_object(val) == val

    def test_unicode_accents(self):
        assert sanitize_kg_object("São Paulo, Brasil") == "São Paulo, Brasil"

    def test_unicode_cjk(self):
        assert sanitize_kg_object("東京タワー") == "東京タワー"

    def test_emoji(self):
        assert sanitize_kg_object("happy 😊") == "happy 😊"

    def test_max_length_boundary(self):
        val = "a" * MAX_KG_OBJECT_LENGTH
        assert sanitize_kg_object(val) == val


# ── Rejection: values that MUST be rejected ──────────────────────────────────


class TestSanitizeKgObjectRejects:
    def test_empty_string(self):
        with pytest.raises(ValueError, match="must be a non-empty string"):
            sanitize_kg_object("")

    def test_whitespace_only(self):
        with pytest.raises(ValueError, match="must be a non-empty string"):
            sanitize_kg_object("   ")

    def test_none(self):
        with pytest.raises(ValueError, match="must be a non-empty string"):
            sanitize_kg_object(None)

    def test_non_string_int(self):
        with pytest.raises(ValueError, match="must be a non-empty string"):
            sanitize_kg_object(42)

    def test_non_string_list(self):
        with pytest.raises(ValueError, match="must be a non-empty string"):
            sanitize_kg_object(["a", "b"])

    def test_exceeds_max_length(self):
        with pytest.raises(ValueError, match="exceeds maximum length"):
            sanitize_kg_object("x" * (MAX_KG_OBJECT_LENGTH + 1))

    def test_null_byte(self):
        with pytest.raises(ValueError, match="null bytes"):
            sanitize_kg_object("hello\x00world")

    def test_path_traversal_dotdot(self):
        with pytest.raises(ValueError, match="invalid path characters"):
            sanitize_kg_object("../../etc/passwd")

    def test_path_traversal_forward_slash(self):
        with pytest.raises(ValueError, match="invalid path characters"):
            sanitize_kg_object("etc/passwd")

    def test_path_traversal_backslash(self):
        with pytest.raises(ValueError, match="invalid path characters"):
            sanitize_kg_object("etc\\passwd")

    def test_embedded_null_byte(self):
        with pytest.raises(ValueError, match="null bytes"):
            sanitize_kg_object("before\x00after")


# ── Stripping behaviour ─────────────────────────────────────────────────────


class TestSanitizeKgObjectStripping:
    def test_leading_spaces_stripped(self):
        assert sanitize_kg_object("  hello") == "hello"

    def test_trailing_spaces_stripped(self):
        assert sanitize_kg_object("hello  ") == "hello"

    def test_both_sides_stripped(self):
        assert sanitize_kg_object("  hello  ") == "hello"

    def test_tabs_stripped(self):
        assert sanitize_kg_object("\thello\t") == "hello"

    def test_newlines_stripped(self):
        assert sanitize_kg_object("\nhello\n") == "hello"


# ── Custom field_name in error messages ──────────────────────────────────────


class TestSanitizeKgObjectFieldName:
    def test_default_field_name(self):
        with pytest.raises(ValueError, match="object"):
            sanitize_kg_object("")

    def test_custom_field_name(self):
        with pytest.raises(ValueError, match="target_entity"):
            sanitize_kg_object("", field_name="target_entity")


# ── Confirm sanitize_name still rejects punctuation (regression guard) ───────


class TestSanitizeNameStillStrict:
    """Ensure we didn't accidentally loosen sanitize_name."""

    def test_rejects_comma(self):
        with pytest.raises(ValueError):
            sanitize_name("chess, swimming", "test")

    def test_rejects_colon(self):
        with pytest.raises(ValueError):
            sanitize_name("role: engineer", "test")

    def test_rejects_parentheses(self):
        with pytest.raises(ValueError):
            sanitize_name("Alice (daughter)", "test")

    def test_accepts_simple_name(self):
        assert sanitize_name("Alice", "test") == "Alice"

    def test_accepts_name_with_apostrophe(self):
        assert sanitize_name("O'Brien", "test") == "O'Brien"


# ── Integration: tool_kg_add with descriptive objects ────────────────────────


class TestToolKgAddWithPunctuation:
    """End-to-end tests through the MCP tool handler."""

    def _patch(self, monkeypatch, config, kg):
        from mempalace import mcp_server
        monkeypatch.setattr(mcp_server, "_config", config)
        monkeypatch.setattr(mcp_server, "_kg", kg)

    def test_add_comma_object(self, monkeypatch, config, palace_path, kg):
        self._patch(monkeypatch, config, kg)
        from mempalace.mcp_server import tool_kg_add

        result = tool_kg_add(
            subject="Max",
            predicate="hobbies",
            object="chess, swimming, reading",
        )
        assert result["success"] is True
        assert "chess, swimming, reading" in result["fact"]

    def test_add_colon_object(self, monkeypatch, config, palace_path, kg):
        self._patch(monkeypatch, config, kg)
        from mempalace.mcp_server import tool_kg_add

        result = tool_kg_add(
            subject="Alice",
            predicate="occupation",
            object="role: senior engineer",
        )
        assert result["success"] is True

    def test_add_parentheses_object(self, monkeypatch, config, palace_path, kg):
        self._patch(monkeypatch, config, kg)
        from mempalace.mcp_server import tool_kg_add

        result = tool_kg_add(
            subject="Max",
            predicate="born",
            object="April 1, 2015 (age 11)",
        )
        assert result["success"] is True

    def test_add_semicolon_object(self, monkeypatch, config, palace_path, kg):
        self._patch(monkeypatch, config, kg)
        from mempalace.mcp_server import tool_kg_add

        result = tool_kg_add(
            subject="Alice",
            predicate="known_for",
            object="engineering; leadership; mentoring",
        )
        assert result["success"] is True

    def test_add_complex_descriptive_object(self, monkeypatch, config, palace_path, kg):
        self._patch(monkeypatch, config, kg)
        from mempalace.mcp_server import tool_kg_add

        result = tool_kg_add(
            subject="Max",
            predicate="note",
            object="Born April 1, 2015 (age 11); loves chess, swimming, and reading!",
            valid_from="2015-04-01",
        )
        assert result["success"] is True

    def test_subject_still_validated_strictly(self, monkeypatch, config, palace_path, kg):
        self._patch(monkeypatch, config, kg)
        from mempalace.mcp_server import tool_kg_add

        result = tool_kg_add(
            subject="bad, subject",
            predicate="likes",
            object="coffee",
        )
        assert result["success"] is False
        assert "invalid characters" in result["error"]

    def test_predicate_still_validated_strictly(self, monkeypatch, config, palace_path, kg):
        self._patch(monkeypatch, config, kg)
        from mempalace.mcp_server import tool_kg_add

        result = tool_kg_add(
            subject="Alice",
            predicate="likes, loves",
            object="coffee",
        )
        assert result["success"] is False
        assert "invalid characters" in result["error"]

    def test_object_rejects_path_traversal(self, monkeypatch, config, palace_path, kg):
        self._patch(monkeypatch, config, kg)
        from mempalace.mcp_server import tool_kg_add

        result = tool_kg_add(
            subject="Alice",
            predicate="likes",
            object="../../etc/passwd",
        )
        assert result["success"] is False
        assert "path characters" in result["error"]

    def test_object_rejects_null_byte(self, monkeypatch, config, palace_path, kg):
        self._patch(monkeypatch, config, kg)
        from mempalace.mcp_server import tool_kg_add

        result = tool_kg_add(
            subject="Alice",
            predicate="likes",
            object="coffee\x00injection",
        )
        assert result["success"] is False
        assert "null bytes" in result["error"]

    def test_add_then_query_roundtrip(self, monkeypatch, config, palace_path, kg):
        """Values with punctuation survive a write→read roundtrip."""
        self._patch(monkeypatch, config, kg)
        from mempalace.mcp_server import tool_kg_add, tool_kg_query

        tool_kg_add(
            subject="Max",
            predicate="description",
            object="age 11, loves chess & swimming",
        )
        result = tool_kg_query(entity="Max")
        objects = [f["object"] for f in result["facts"]]
        assert "age 11, loves chess & swimming" in objects
