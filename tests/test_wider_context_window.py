"""Tests for the wider-context-window improvement.

The original _collect_contexts returns up to 3 lines × 240 chars = 720 chars
of context per candidate. This is too little for Haiku to disambiguate
tokens like 'Bash' (shell vs name) or 'Cost' (noun vs name).

The new behavior: 1 line × 2000 chars by default, giving Haiku a single
rich window per candidate. Same total token cost as the 3-line approach
but much better signal density for disambiguation."""
import unittest
from mempalace.llm_refine import (
    CONTEXT_LINES_PER_CANDIDATE,
    CONTEXT_WINDOW_CHARS,
    _collect_contexts,
)


class TestWiderContextWindow(unittest.TestCase):
    def test_default_window_is_2000_chars(self):
        """Default CONTEXT_WINDOW_CHARS should be 2000 (was 240)."""
        self.assertEqual(CONTEXT_WINDOW_CHARS, 2000,
                         "default window should be 2000 chars for rich disambiguation context")

    def test_default_lines_is_1(self):
        """Default CONTEXT_LINES_PER_CANDIDATE should be 1 — one rich window
        rather than multiple short ones."""
        self.assertEqual(CONTEXT_LINES_PER_CANDIDATE, 1,
                         "default should be 1 rich window, not 3 short ones")

    def test_collect_contexts_returns_large_window_by_default(self):
        """When given a long line containing the candidate, the default
        collection should return up to 2000 chars, not 240."""
        long_line = "Before context. " + "x" * 800 + " Paris is a city. " + "y" * 800 + " After."
        out = _collect_contexts([long_line], "Paris")
        self.assertEqual(len(out), 1, "should return exactly 1 line at default")
        self.assertGreater(len(out[0]), 500,
                           "default window should be wide enough to disambiguate "
                           "(>500 chars); got %d" % len(out[0]))

    def test_window_chars_is_configurable(self):
        """Caller can pass window_chars to override default (e.g. to use 240
        for legacy behavior or 4000 for even richer context)."""
        line = "Paris " + ("x" * 3000)
        out_small = _collect_contexts([line], "Paris", window_chars=240)
        self.assertLessEqual(len(out_small[0]), 240)
        out_big = _collect_contexts([line], "Paris", window_chars=4000)
        self.assertGreater(len(out_big[0]), 240)


if __name__ == "__main__":
    unittest.main()
