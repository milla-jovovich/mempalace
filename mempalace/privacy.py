"""
privacy.py — Progressive disclosure + <private> tag handling.

Two responsibilities:

1. ``redact_private(text)`` — strip ``<private>...</private>`` blocks
   (case-insensitive, multiline) from memory content before it gets
   stored or embedded. Returns the cleaned string and a boolean
   indicating whether the *entire* input was private (i.e. after
   stripping + whitespace trim, nothing remains).

2. ``summarize_for_search(text, n_chars)`` — collapse internal
   whitespace to single spaces and truncate to ``n_chars`` code
   points, backing up to the last space on ASCII boundaries so
   words aren't chopped. Appends an ellipsis when truncated.

These helpers are used by ``mcp_server.tool_search`` (progressive
disclosure — default responses show a short summary), and by
``tool_add_drawer`` / ``tool_diary_write`` (private-tag filtering
before sanitize + embed).
"""

from __future__ import annotations

import re

# ``<private>...</private>`` — case-insensitive, dot matches newline,
# non-greedy so multiple blocks in one string are each stripped
# individually rather than merged.
PRIVATE_TAG_RE = re.compile(r"<private>.*?</private>", re.DOTALL | re.IGNORECASE)

# Whitespace run — used by summarize_for_search to collapse runs of
# spaces/tabs/newlines to a single space before truncation.
_WS_RUN_RE = re.compile(r"\s+")


def redact_private(text: str) -> tuple[str, bool]:
    """Strip ``<private>...</private>`` blocks from ``text``.

    Returns a ``(cleaned, is_fully_private)`` tuple:

    - ``cleaned`` — input with every ``<private>...</private>`` block
      removed. Whitespace adjacent to stripped blocks is left intact
      (callers can re-sanitize if they need tight whitespace rules).
    - ``is_fully_private`` — True iff after stripping and calling
      ``.strip()`` the remaining string is empty. Callers typically
      reject the write when this is True so that fully-private
      entries don't leak via metadata, drawer ID, or embedding.

    The regex is case-insensitive (``<PRIVATE>`` works too) and
    multiline (tags can span newlines).
    """
    if not isinstance(text, str):
        raise TypeError("redact_private expects a str")

    cleaned = PRIVATE_TAG_RE.sub("", text)
    is_fully_private = cleaned.strip() == ""
    return cleaned, is_fully_private


def summarize_for_search(text: str, n_chars: int = 30) -> str:
    """Collapse whitespace and truncate ``text`` to ``n_chars`` code points.

    Behaviour:

    - All internal whitespace runs (spaces, tabs, newlines) become a
      single space.
    - Leading/trailing whitespace is stripped.
    - If the collapsed text is <= ``n_chars`` code points long, it is
      returned as-is (no ellipsis appended).
    - Otherwise it is truncated to ``n_chars`` code points. If the
      truncation point sits mid-word on ASCII text, we back up to
      the last space so words aren't chopped. For Chinese / CJK and
      other scripts that don't use spaces between words, truncation
      happens on the code-point boundary.
    - A single ellipsis character (U+2026) is appended to signal
      truncation.

    ``n_chars`` must be a positive integer. Zero or negative values
    return an empty string.
    """
    if not isinstance(text, str):
        raise TypeError("summarize_for_search expects a str")
    if n_chars <= 0:
        return ""

    collapsed = _WS_RUN_RE.sub(" ", text).strip()

    if len(collapsed) <= n_chars:
        return collapsed

    truncated = collapsed[:n_chars]

    # If the character immediately after the truncation point is an
    # ASCII word character, we chopped mid-word — back up to the last
    # space inside our window. Only applies when the surrounding text
    # is ASCII; CJK scripts have no space-based word boundaries.
    next_char = collapsed[n_chars]
    if next_char.isascii() and (next_char.isalnum() or next_char == "_"):
        last_space = truncated.rfind(" ")
        if last_space > 0:
            truncated = truncated[:last_space]

    return truncated.rstrip() + "\u2026"
