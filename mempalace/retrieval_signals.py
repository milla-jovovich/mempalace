"""
retrieval_signals.py — Shared retrieval hints computed at ingest and query time.

The benchmark harness proved that two lightweight signals consistently improve
retrieval quality:

1. Hall routing: classify memories into coarse semantic halls such as facts,
   events, preferences, and assistant advice.
2. Preference-support text: synthesize a short embedding-friendly document from
   phrases like "I prefer X" or "I've been struggling with Y".

This module keeps those heuristics in one place so miners can persist them and
search strategies can interpret them consistently. The production code
intentionally uses the stable v3-era heuristics rather than the benchmark's
question-specific v4 tweaks, because the goal here is generalization, not
optimizing for a handful of known benchmark misses.
"""

from __future__ import annotations

import re

HALL_PREFERENCES = "hall_preferences"
HALL_FACTS = "hall_facts"
HALL_EVENTS = "hall_events"
HALL_ASSISTANT = "hall_assistant_advice"
HALL_GENERAL = "hall_general"

_ASSISTANT_REFERENCE_TRIGGERS = (
    "you suggested",
    "what did you suggest",
    "you told me",
    "what did you tell me",
    "you mentioned",
    "you said",
    "you recommended",
    "what did you recommend",
    "you provided",
    "you listed",
    "you gave",
    "remind me what you",
    "you came up with",
    "you explained",
)

_PREFERENCE_PATTERNS = [
    r"i(?:'ve been| have been) having (?:trouble|issues?|problems?) with ([^,\.!?]{5,80})",
    r"i(?:'ve been| have been) feeling ([^,\.!?]{5,60})",
    r"i(?:'ve been| have been) (?:struggling|dealing) with ([^,\.!?]{5,80})",
    r"i(?:'ve been| have been) (?:worried|concerned) about ([^,\.!?]{5,80})",
    r"i(?:'m| am) (?:worried|concerned) about ([^,\.!?]{5,80})",
    r"i prefer ([^,\.!?]{5,60})",
    r"i usually ([^,\.!?]{5,60})",
    r"i(?:'ve been| have been) (?:trying|attempting) to ([^,\.!?]{5,80})",
    r"i(?:'ve been| have been) (?:considering|thinking about) ([^,\.!?]{5,80})",
    r"lately[,\s]+(?:i've been|i have been|i'm|i am) ([^,\.!?]{5,80})",
    r"recently[,\s]+(?:i've been|i have been|i'm|i am) ([^,\.!?]{5,80})",
    r"i(?:'ve been| have been) (?:working on|focused on|interested in) ([^,\.!?]{5,80})",
    r"i want to ([^,\.!?]{5,60})",
    r"i(?:'m| am) looking (?:to|for) ([^,\.!?]{5,60})",
    r"i(?:'m| am) thinking (?:about|of) ([^,\.!?]{5,60})",
    r"i(?:'ve been| have been) (?:noticing|experiencing) ([^,\.!?]{5,80})",
]


def infer_ingest_mode(
    content: str,
    metadata: dict | None = None,
    default: str = "project",
) -> str:
    """Infer the canonical ingest mode for a raw drawer.

    Older palaces predate the explicit ``ingest_mode`` metadata now used by
    retrieval heuristics. Repair/backfill needs one place to recover that mode
    from whatever hints survived: a stored ``ingest_mode`` value, legacy
    ``extract_mode`` metadata, or the transcript-like ``> user`` formatting
    used by conversation mining.
    """
    metadata = metadata or {}

    # Respect any explicit ingest mode first, but normalize older spellings so
    # the rest of the code only has to reason about the canonical values.
    stored = metadata.get("ingest_mode")
    if isinstance(stored, str):
        normalized = stored.strip().lower()
        if normalized in {"project", "projects"}:
            return "project"
        if normalized in {"convo", "convos", "conversation", "conversations"}:
            return "convos"

    # Conversation mining has historically stored extract_mode even when the
    # higher-level ingest mode was absent, so keep honoring that signal.
    if metadata.get("extract_mode"):
        return "convos"

    looks_like_transcript = "\n>" in content or content.lstrip().startswith(">")
    if looks_like_transcript:
        return "convos"

    return default


def _split_dialogue_content(content: str, ingest_mode: str | None = None) -> tuple[str, str]:
    """Separate user and assistant text for transcript-style chunks.

    Conversation mining stores transcript chunks in a compact `> user` then
    assistant-response format. Project/code files are plain documents. The hall
    and preference heuristics want access to "what the user said" separately
    from "what the assistant recommended", so we split when the content clearly
    looks transcript-like and otherwise treat the whole document as user text.
    """
    looks_like_transcript = ingest_mode == "convos" or "\n>" in content or content.lstrip().startswith(">")
    if not looks_like_transcript:
        return content, ""

    user_lines = []
    assistant_lines = []
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line or line == "---":
            continue
        if line.startswith(">"):
            user_lines.append(line.lstrip("> ").strip())
        else:
            assistant_lines.append(line)

    return "\n".join(user_lines).strip(), "\n".join(assistant_lines).strip()


def extract_preference_signals(
    content: str,
    ingest_mode: str | None = None,
    limit: int = 10,
) -> list[str]:
    """Extract preference or concern phrases from a memory chunk.

    The returned phrases are short enough to embed well and concrete enough to
    bridge the benchmark's main vocabulary-gap failures.
    """
    user_text, _assistant_text = _split_dialogue_content(content, ingest_mode=ingest_mode)
    text = user_text.lower()

    mentions = []
    for pattern in _PREFERENCE_PATTERNS:
        for match in re.findall(pattern, text, re.IGNORECASE):
            if isinstance(match, tuple):
                match = " ".join(match)
            clean = match.strip().rstrip(".,;!? ")
            if 5 <= len(clean) <= 80:
                mentions.append(clean)

    # Preserve first-seen order so the support text remains stable across
    # repeated mining runs and deterministic IDs keep working.
    unique = []
    seen = set()
    for mention in mentions:
        if mention not in seen:
            seen.add(mention)
            unique.append(mention)

    collapsed = []
    for mention in unique:
        # The heuristics intentionally overlap so we can catch both general
        # preference statements and more structured "recently I've been..."
        # phrasing. When two matches describe the same idea, keep the more
        # specific phrase and drop the nested duplicate so support docs stay
        # concise and do not overweight one underlying concern.
        if any(mention != existing and mention in existing for existing in collapsed):
            continue
        collapsed = [existing for existing in collapsed if existing == mention or existing not in mention]
        collapsed.append(mention)

    return collapsed[:limit]


def build_preference_support_document(
    content: str,
    ingest_mode: str | None = None,
) -> dict | None:
    """Build the synthetic preference-support document for one raw drawer.

    This returns a compact structure that miners can persist into the support
    collection. Search uses the helper document's embedding to find the raw
    drawer when the user's later question uses different vocabulary.
    """
    signals = extract_preference_signals(content, ingest_mode=ingest_mode)
    if not signals:
        return None

    return {
        "text": "User has mentioned: " + "; ".join(signals),
        "signals": signals,
    }


def classify_document_hall(content: str, ingest_mode: str | None = None) -> str:
    """Classify a memory chunk into the production hall taxonomy."""
    user_text, assistant_text = _split_dialogue_content(content, ingest_mode=ingest_mode)
    user_lower = user_text.lower()
    assistant_lower = assistant_text.lower()
    combined_lower = f"{user_lower}\n{assistant_lower}".strip()

    pref_signals = [
        "i prefer",
        "i usually",
        "i've been having trouble",
        "i've been feeling",
        "i've been struggling",
        "i want to",
        "i'm worried",
        "i've been thinking",
        "i've been considering",
        "lately i",
        "recently i",
        "i tend to",
    ]
    if any(signal in user_lower for signal in pref_signals):
        return HALL_PREFERENCES

    # Assistant-advice is only meaningful when the chunk actually contains a
    # distinct assistant segment. Project files often contain numbered lists;
    # we do not want those to masquerade as "assistant advice" halls.
    if assistant_lower:
        assistant_signals = [
            "i suggest",
            "i recommend",
            "here are",
            "you might want to",
            "option 1",
            "option 2",
            "1.",
            "2.",
            "3.",
            "first,",
            "second,",
            "you could try",
            "i would recommend",
            "my recommendation",
        ]
        if sum(1 for signal in assistant_signals if signal in assistant_lower) >= 2:
            return HALL_ASSISTANT

    event_signals = [
        "milestone",
        "graduation",
        "promotion",
        "anniversary",
        "birthday",
        "moved",
        "started",
        "finished",
        "completed",
        "launched",
        "opened",
        "achieved",
        "won",
        "accepted",
        "hired",
        "married",
        "born",
    ]
    if any(signal in combined_lower for signal in event_signals):
        return HALL_EVENTS

    fact_signals = [
        "degree",
        "major",
        "university",
        "college",
        "job",
        "position",
        "role",
        "company",
        "city",
        "country",
        "street",
        "born in",
        "grew up",
        "studied",
        "works at",
        "lives in",
        "years old",
        "salary",
        "budget",
    ]
    if sum(1 for signal in fact_signals if signal in combined_lower) >= 2:
        return HALL_FACTS

    return HALL_GENERAL


def classify_question_halls(question: str) -> list[str]:
    """Infer which halls are most likely to hold the answer for a query."""
    query = question.lower()

    if any(trigger in query for trigger in _ASSISTANT_REFERENCE_TRIGGERS):
        return [HALL_ASSISTANT, HALL_GENERAL]

    if any(
        trigger in query
        for trigger in [
            "i've been having trouble",
            "i've been feeling",
            "i prefer",
            "i usually",
            "battery",
            "lately",
            "recently been",
            "struggling with",
        ]
    ):
        return [HALL_PREFERENCES, HALL_GENERAL]

    if any(
        trigger in query
        for trigger in [
            "milestone",
            "when did",
            "what happened",
            "achievement",
            "ago",
            "last week",
            "last month",
            "last year",
            "four weeks",
            "three months",
        ]
    ):
        return [HALL_EVENTS, HALL_FACTS, HALL_GENERAL]

    if any(
        trigger in query
        for trigger in [
            "degree",
            "study",
            "graduate",
            "major",
            "job",
            "work",
            "live",
            "born",
            "city",
            "country",
            "company",
            "school",
        ]
    ):
        return [HALL_FACTS, HALL_GENERAL]

    return [HALL_GENERAL]


def is_assistant_reference_query(question: str) -> bool:
    """True when the query is explicitly asking about prior assistant output."""
    query = question.lower()
    return any(trigger in query for trigger in _ASSISTANT_REFERENCE_TRIGGERS)
