"""
test_privacy.py — Unit tests for <private> redaction + search summary helpers.

Covers:
- redact_private: basic partial strip, fully-private detection,
  case-insensitivity, multiline blocks, multiple blocks.
- summarize_for_search: code-point truncation for CJK, ASCII word
  boundary backup, short-input passthrough, ellipsis appending.
"""

import pytest

from mempalace.privacy import (
    PRIVATE_TAG_RE,
    redact_private,
    summarize_for_search,
)


# ── redact_private ─────────────────────────────────────────────────────


class TestRedactPrivate:
    def test_partial_private_strips_block_only(self):
        cleaned, fully = redact_private("hello <private>secret</private> world")
        # The <private>...</private> substring is removed entirely; the
        # two surrounding spaces are left alone, so we get a double space
        # where the block used to be. Callers re-run sanitize_content() on
        # the result if they need tidy whitespace.
        assert cleaned == "hello  world"
        assert fully is False

    def test_fully_private_detected(self):
        cleaned, fully = redact_private("<private>all</private>")
        assert cleaned == ""
        assert fully is True

    def test_fully_private_with_surrounding_whitespace(self):
        # Only whitespace remains after stripping -> still fully private.
        cleaned, fully = redact_private("  \n  <private>secret</private>  \n  ")
        assert cleaned.strip() == ""
        assert fully is True

    def test_case_insensitive(self):
        cleaned, fully = redact_private("before <PRIVATE>x</PRIVATE> after")
        assert "<PRIVATE>" not in cleaned
        assert "x" not in cleaned
        assert "before" in cleaned and "after" in cleaned
        assert fully is False

    def test_mixed_case_tags(self):
        cleaned, fully = redact_private("a <Private>x</Private> b <pRiVaTe>y</pRiVaTe> c")
        assert "x" not in cleaned and "y" not in cleaned
        assert "a" in cleaned and "b" in cleaned and "c" in cleaned
        assert fully is False

    def test_multiline_block(self):
        cleaned, fully = redact_private("before <private>\nfoo\nbar\n</private> after")
        assert "foo" not in cleaned
        assert "bar" not in cleaned
        assert "before" in cleaned and "after" in cleaned
        assert fully is False

    def test_multiple_blocks(self):
        cleaned, fully = redact_private(
            "keep1 <private>drop1</private> keep2 <private>drop2</private> keep3"
        )
        assert "drop1" not in cleaned
        assert "drop2" not in cleaned
        assert "keep1" in cleaned and "keep2" in cleaned and "keep3" in cleaned
        assert fully is False

    def test_no_tags_returns_input(self):
        cleaned, fully = redact_private("plain text, nothing private")
        assert cleaned == "plain text, nothing private"
        assert fully is False

    def test_empty_string_is_fully_private(self):
        cleaned, fully = redact_private("")
        assert cleaned == ""
        assert fully is True

    def test_non_greedy_match(self):
        # Ensure non-greedy behavior: two separate blocks don't get
        # merged into one giant strip that also eats the text between.
        cleaned, _ = redact_private("<private>a</private>MIDDLE<private>b</private>")
        assert cleaned == "MIDDLE"

    def test_regex_is_compiled_and_exposed(self):
        # Public constant — callers may want to reuse it.
        assert PRIVATE_TAG_RE.search("<private>x</private>") is not None

    def test_non_string_input_raises(self):
        with pytest.raises(TypeError):
            redact_private(None)  # type: ignore[arg-type]


# ── summarize_for_search ───────────────────────────────────────────────


class TestSummarizeForSearch:
    def test_short_input_returned_verbatim(self):
        out = summarize_for_search("short", 30)
        assert out == "short"
        assert "\u2026" not in out

    def test_whitespace_collapsed(self):
        out = summarize_for_search("a  b\tc\n\nd", 30)
        assert out == "a b c d"

    def test_ascii_backs_up_to_word_boundary(self):
        # 30-char cutoff lands mid-word "management"; should back up to
        # the previous space and append the ellipsis.
        text = "The authentication module uses JWT tokens for session management."
        out = summarize_for_search(text, 30)
        assert out.endswith("\u2026")
        # Must not chop "management" in half.
        assert "managem\u2026" not in out
        # Length includes ellipsis, but <= n_chars + 1.
        assert len(out) <= 31

    def test_ascii_short_word_keeps_last_full_word(self):
        # "hello world foo" — at n=10, pos 10 is 'f' inside "foo",
        # back up to space at idx 5 -> "hello" + ellipsis.
        out = summarize_for_search("hello world foo bar baz qux", 10)
        assert out == "hello\u2026"

    def test_cjk_truncates_on_code_point(self):
        text = "今天天氣很好我們去散步吧這是一個中文測試句子足夠長"
        out = summarize_for_search(text, 10)
        # Ten Chinese code points + ellipsis.
        assert out == text[:10] + "\u2026"
        assert len(out) == 11

    def test_ellipsis_appended_on_truncation(self):
        out = summarize_for_search("a" * 100, 5)
        assert out.endswith("\u2026")
        # 5 a's + ellipsis; no word boundary to back up to so we keep
        # the full window.
        assert out == "aaaaa\u2026"

    def test_zero_n_chars_returns_empty(self):
        assert summarize_for_search("hello", 0) == ""

    def test_negative_n_chars_returns_empty(self):
        assert summarize_for_search("hello", -5) == ""

    def test_non_string_input_raises(self):
        with pytest.raises(TypeError):
            summarize_for_search(None, 30)  # type: ignore[arg-type]
