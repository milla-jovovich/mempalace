"""
tests/test_spellcheck.py — Tests for mempalace/spellcheck.py

Covers:
  - _should_skip() for all skip categories
  - spellcheck_user_text() — both the autocorrect-available and fallback paths
"""

import unittest.mock as mock

import pytest

from mempalace.spellcheck import _should_skip, spellcheck_user_text


# ─────────────────────────────────────────────────────────────────────────────
# _should_skip — pure, no I/O
# ─────────────────────────────────────────────────────────────────────────────

EMPTY_NAMES: set = set()


class TestShouldSkip:
    """Tests for _should_skip(token, known_names)."""

    # --- length threshold ---------------------------------------------------

    def test_skips_single_char(self):
        assert _should_skip("a", EMPTY_NAMES) is True

    def test_skips_two_chars(self):
        assert _should_skip("ok", EMPTY_NAMES) is True

    def test_skips_three_chars(self):
        assert _should_skip("the", EMPTY_NAMES) is True

    def test_does_not_skip_four_chars(self):
        # A plain four-letter word with no special patterns should NOT be
        # auto-skipped on length alone.
        assert _should_skip("word", EMPTY_NAMES) is False

    # --- digits -------------------------------------------------------------

    def test_skips_token_with_digit(self):
        assert _should_skip("3am", EMPTY_NAMES) is True

    def test_skips_version_string(self):
        assert _should_skip("bge-large-v1.5", EMPTY_NAMES) is True

    def test_skips_top_number(self):
        assert _should_skip("top-10", EMPTY_NAMES) is True

    # --- CamelCase ----------------------------------------------------------

    def test_skips_camelcase(self):
        assert _should_skip("ChromaDB", EMPTY_NAMES) is True

    def test_skips_mempalace_camel(self):
        assert _should_skip("MemPalace", EMPTY_NAMES) is True

    def test_skips_longmemeval(self):
        assert _should_skip("LongMemEval", EMPTY_NAMES) is True

    # --- ALL_CAPS -----------------------------------------------------------

    def test_skips_allcaps(self):
        assert _should_skip("NDCG", EMPTY_NAMES) is True

    def test_skips_allcaps_underscores(self):
        assert _should_skip("MAX_RESULTS", EMPTY_NAMES) is True

    # --- Technical tokens (hyphens / underscores) ---------------------------

    def test_skips_hyphenated(self):
        assert _should_skip("fine-tuned", EMPTY_NAMES) is True

    def test_skips_underscored(self):
        assert _should_skip("train_test", EMPTY_NAMES) is True

    def test_skips_hyphen_path(self):
        assert _should_skip("bge-large", EMPTY_NAMES) is True

    # --- URLs and paths -----------------------------------------------------

    def test_skips_https_url(self):
        assert _should_skip("https://example.com", EMPTY_NAMES) is True

    def test_skips_www_url(self):
        assert _should_skip("www.example.com", EMPTY_NAMES) is True

    def test_skips_tilde_path(self):
        assert _should_skip("~/projects", EMPTY_NAMES) is True

    def test_skips_users_path(self):
        assert _should_skip("/Users/jan/code", EMPTY_NAMES) is True

    def test_skips_dotted_extension(self):
        # Ends with a file extension like .py
        assert _should_skip("script.py", EMPTY_NAMES) is True

    # --- Code / Markdown patterns -------------------------------------------

    def test_skips_backtick_token(self):
        assert _should_skip("`code`", EMPTY_NAMES) is True

    def test_skips_markdown_bold(self):
        assert _should_skip("**bold**", EMPTY_NAMES) is True

    def test_skips_curly_brace(self):
        assert _should_skip("{key}", EMPTY_NAMES) is True

    # --- known_names set ----------------------------------------------------

    def test_skips_known_name_exact(self):
        assert _should_skip("riley", {"riley", "sam"}) is True

    def test_skips_known_name_case_insensitive(self):
        # Token "Riley" lowered should still match
        assert _should_skip("Riley", {"riley"}) is True

    def test_does_not_skip_unknown_word(self):
        # Plain lowercase word not in known_names — should not be skipped
        assert _should_skip("question", EMPTY_NAMES) is False

    def test_does_not_skip_with_unrelated_names(self):
        assert _should_skip("before", {"riley", "sam"}) is False


# ─────────────────────────────────────────────────────────────────────────────
# spellcheck_user_text — fallback (no autocorrect) path
# ─────────────────────────────────────────────────────────────────────────────

class TestSpellcheckUserTextFallback:
    """When autocorrect is not installed, text must be returned unchanged."""

    def _run_without_autocorrect(self, text, **kwargs):
        import mempalace.spellcheck as sc
        with mock.patch.object(sc, "_get_speller", return_value=None):
            return spellcheck_user_text(text, **kwargs)

    def test_plain_text_unchanged(self):
        msg = "lsresdy knoe the question befor"
        assert self._run_without_autocorrect(msg) == msg

    def test_empty_string_unchanged(self):
        assert self._run_without_autocorrect("") == ""

    def test_multiline_unchanged(self):
        msg = "first line\nsecond line with typo"
        assert self._run_without_autocorrect(msg) == msg

    def test_known_names_kwarg_accepted(self):
        msg = "some text here"
        assert self._run_without_autocorrect(msg, known_names={"riley"}) == msg

    def test_whitespace_only_unchanged(self):
        msg = "   \t  "
        assert self._run_without_autocorrect(msg) == msg

    def test_technical_tokens_unchanged(self):
        msg = "ChromaDB bge-large-en-v1.5 NDCG@10 R@5"
        assert self._run_without_autocorrect(msg) == msg

    def test_url_unchanged(self):
        msg = "see https://example.com for details"
        assert self._run_without_autocorrect(msg) == msg


# ─────────────────────────────────────────────────────────────────────────────
# spellcheck_user_text — with a mock speller
# ─────────────────────────────────────────────────────────────────────────────

class TestSpellcheckUserTextWithSpeller:
    """
    Tests using a deterministic mock speller so we don't depend on the
    autocorrect package being installed.
    """

    def _run_with_mock_speller(self, text, corrections: dict, known_names=None):
        """
        Inject a mock speller that returns corrections[word] when available,
        else returns the original word unchanged.
        Patches _get_system_words to return an empty set so no word is
        pre-filtered as already-valid English.
        """
        import mempalace.spellcheck as sc

        def fake_speller(word):
            return corrections.get(word, word)

        with mock.patch.object(sc, "_get_speller", return_value=fake_speller), \
             mock.patch.object(sc, "_get_system_words", return_value=set()), \
             mock.patch.object(sc, "_load_known_names", return_value=known_names or set()):
            return spellcheck_user_text(text, known_names=known_names)

    def test_corrects_simple_typo(self):
        result = self._run_with_mock_speller(
            "I knoe the answer",
            {"knoe": "know"},
        )
        assert "know" in result
        assert "knoe" not in result

    def test_preserves_surrounding_words(self):
        result = self._run_with_mock_speller(
            "please help with this",
            {},
        )
        assert result == "please help with this"

    def test_reattaches_trailing_punctuation(self):
        result = self._run_with_mock_speller(
            "Is that corect?",
            {"corect": "correct"},
        )
        assert result.endswith("correct?")

    def test_trailing_comma_reattached(self):
        result = self._run_with_mock_speller(
            "yes, that is corect,",
            {"corect": "correct"},
        )
        assert result.endswith("correct,")

    def test_capitalized_word_not_corrected(self):
        result = self._run_with_mock_speller(
            "Riley is here",
            {"Riley": "Wiley"},
        )
        assert "Riley" in result

    def test_skips_short_words(self):
        result = self._run_with_mock_speller(
            "do it now",
            {"do": "does", "it": "its", "now": "not"},
        )
        assert result == "do it now"

    def test_skips_camelcase(self):
        result = self._run_with_mock_speller(
            "Use ChromaDB today",
            {"ChromaDB": "Chrome"},
        )
        assert "ChromaDB" in result

    def test_skips_hyphenated_token(self):
        result = self._run_with_mock_speller(
            "fine-tuned model",
            {"fine-tuned": "fine-tune"},
        )
        assert "fine-tuned" in result

    def test_skips_url(self):
        result = self._run_with_mock_speller(
            "visit https://example.com please",
            {"https://example.com": "http://changed.com"},
        )
        assert "https://example.com" in result

    def test_skips_token_with_digit(self):
        result = self._run_with_mock_speller(
            "woke up at 3am today",
            {"3am": "3pm"},
        )
        assert "3am" in result

    def test_known_names_preserved(self):
        result = self._run_with_mock_speller(
            "mempalace cant store that",
            {"mempalace": "someplace", "cant": "can"},
            known_names={"mempalace"},
        )
        assert "mempalace" in result

    def test_edit_distance_guard_blocks_large_change(self):
        # "word" (4 chars) to "completely" (10 chars): edit distance >> max_edits
        result = self._run_with_mock_speller(
            "just word here",
            {"word": "completely"},
        )
        assert "word" in result

    def test_empty_text_returns_empty(self):
        result = self._run_with_mock_speller("", {})
        assert result == ""

    def test_multiword_sentence(self):
        result = self._run_with_mock_speller(
            "thiss is corect",
            {"thiss": "this", "corect": "correct"},
        )
        assert "this" in result
        assert "correct" in result

    def test_whitespace_preserved(self):
        result = self._run_with_mock_speller(
            "hello   world",
            {},
        )
        assert "   " in result
