"""Trust-type parsing for drawer metadata.

A drawer's ``added_by`` field historically has been a free-form agent name
(e.g. ``"memory-harvest"``, ``"mcp"``, ``"dos-rate-hook"``). Callers that
want to distinguish automated writes from human-authored writes from
LLM-summarized content have had to pattern-match against that free-form
string downstream.

This module defines the three-way prefix convention that callers can opt
into, and the parser that extracts the high-level category. When a drawer
is written with an ``added_by`` that carries a recognized prefix, the
canonical ``add_drawer`` sites (``miner.add_drawer`` and
``mcp_server.tool_add_drawer``) also write a ``trust_type`` metadata field
so consumers (ranking, export, fact_check, council workflows) can filter
without re-parsing strings.

Prefixes:

    mechanical:<hook_name>    automated hook / scheduled job / bridge script
    human:<user>              human-authored drawer (e.g. direct MCP tool call by the user)
    llm_judge:<model_id>      LLM-summarized content; provenance points to the summarizer

An ``added_by`` that does not carry one of these prefixes is treated as
unclassified and ``trust_type`` is left unset. Existing callers are
unaffected.
"""

from __future__ import annotations


TRUST_TYPE_MECHANICAL = "mechanical"
TRUST_TYPE_HUMAN = "human"
TRUST_TYPE_LLM_JUDGE = "llm_judge"

_KNOWN_PREFIXES: tuple[str, ...] = (
    TRUST_TYPE_MECHANICAL,
    TRUST_TYPE_HUMAN,
    TRUST_TYPE_LLM_JUDGE,
)


def parse_trust_type(added_by: str | None) -> str | None:
    """Parse a trust_type category from an ``added_by`` string.

    Returns one of ``"mechanical"``, ``"human"``, ``"llm_judge"`` when
    ``added_by`` starts with the corresponding prefix followed by ``":"``
    and a non-empty specifier. Returns ``None`` otherwise (including for
    ``None``, empty string, or any unrecognized prefix).

    Examples
    --------
    >>> parse_trust_type("mechanical:memory-harvest")
    'mechanical'
    >>> parse_trust_type("human:lucas")
    'human'
    >>> parse_trust_type("llm_judge:claude-opus-4-7")
    'llm_judge'
    >>> parse_trust_type("mcp") is None
    True
    >>> parse_trust_type("") is None
    True
    >>> parse_trust_type(None) is None
    True
    >>> parse_trust_type("mechanical:") is None  # prefix without specifier
    True
    """
    if not added_by or not isinstance(added_by, str):
        return None
    for prefix in _KNOWN_PREFIXES:
        head = prefix + ":"
        if added_by.startswith(head) and len(added_by) > len(head):
            return prefix
    return None
