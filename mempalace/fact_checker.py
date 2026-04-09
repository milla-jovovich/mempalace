"""
fact_checker.py — Rule-based contradiction detection for MemPalace.
====================================================================

Checks assertions in natural language against the knowledge graph to
detect factual conflicts. No API calls, no external dependencies —
pure rule-based pattern matching + KG lookup.

Severity levels:
  RED    — Direct factual contradiction (wrong person, wrong relationship)
  YELLOW — Numeric/temporal mismatch (wrong tenure, wrong date)
  GREEN  — No conflict found (consistent or no data to compare)

Usage:
    from mempalace.fact_checker import check_assertion
    from mempalace.knowledge_graph import KnowledgeGraph

    kg = KnowledgeGraph()
    result = check_assertion("Soren finished the auth migration", kg)
    # => CheckResult(severity="GREEN", ...) or RED/YELLOW with explanation

Works with the MCP server via the mempalace_check_facts tool.
"""

import re
from dataclasses import dataclass, field
from datetime import date
from typing import List, Optional


# ── Result types ─────────────────────────────────────────────────────


@dataclass
class Conflict:
    """A single conflict between an assertion and the knowledge graph."""

    severity: str  # "RED" or "YELLOW"
    entity: str
    field: str  # e.g. "attribution", "tenure", "role", "relationship"
    message: str
    kg_fact: Optional[dict] = None


@dataclass
class CheckResult:
    """Result of checking an assertion against the knowledge graph."""

    severity: str  # "RED", "YELLOW", or "GREEN"
    text: str  # the original assertion
    conflicts: List[Conflict] = field(default_factory=list)
    entities_checked: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Serialize for MCP tool response."""
        result = {
            "severity": self.severity,
            "text": self.text,
            "entities_checked": self.entities_checked,
            "conflicts": [],
        }
        for c in self.conflicts:
            entry = {
                "severity": c.severity,
                "entity": c.entity,
                "field": c.field,
                "message": c.message,
            }
            if c.kg_fact:
                entry["kg_fact"] = c.kg_fact
            result["conflicts"].append(entry)
        return result


# ── Assertion patterns ───────────────────────────────────────────────
# Each pattern extracts (subject, claim_type, object) from natural language.

# Attribution: "X finished/completed/did/built/wrote Y"
_ATTRIBUTION_PATTERN = re.compile(
    r"\b([A-Z][a-z]+(?:\s[A-Z][a-z]+)?)\s+"
    r"(?:finished|completed|did|built|wrote|shipped|deployed|created|designed|implemented|fixed)\s+"
    r"(?:the\s+)?(.+?)(?:\.|$)",
    re.IGNORECASE,
)

# Tenure: "X has been here N years" or "X joined N years ago"
_TENURE_PATTERN = re.compile(
    r"\b([A-Z][a-z]+(?:\s[A-Z][a-z]+)?)\s+"
    r"(?:has been (?:here|at \w+)|(?:has )?worked (?:here|at \w+))\s+"
    r"(?:for\s+)?(\d+)\s+years?",
    re.IGNORECASE,
)

# Role: "X is a/the Y" (where Y is a role-like word)
_ROLE_PATTERN = re.compile(
    r"\b([A-Z][a-z]+(?:\s[A-Z][a-z]+)?)\s+is\s+(?:a|the|an)\s+"
    r"([\w\s]+?)(?:\s+(?:at|of|for|in)\b.*)?(?:\.|,|$)",
    re.IGNORECASE,
)

# Relationship: "X is Y's Z" (e.g. "Max is Alice's son")
_RELATIONSHIP_PATTERN = re.compile(
    r"\b([A-Z][a-z]+(?:\s[A-Z][a-z]+)?)\s+is\s+"
    r"([A-Z][a-z]+(?:\s[A-Z][a-z]+)?)'s\s+"
    r"(daughter|son|child|mother|father|parent|wife|husband|partner|brother|sister|sibling|pet|dog|cat)",
    re.IGNORECASE,
)

# Relationship predicates that map to each other
_RELATIONSHIP_PAIRS = {
    "daughter": ("child_of", "is_child_of", "parent_of"),
    "son": ("child_of", "is_child_of", "parent_of"),
    "child": ("child_of", "is_child_of", "parent_of"),
    "mother": ("parent_of", "is_child_of", "child_of"),
    "father": ("parent_of", "is_child_of", "child_of"),
    "parent": ("parent_of", "is_child_of", "child_of"),
    "wife": ("married_to", "is_partner_of"),
    "husband": ("married_to", "is_partner_of"),
    "partner": ("married_to", "is_partner_of"),
    "brother": ("sibling_of", "is_sibling_of"),
    "sister": ("sibling_of", "is_sibling_of"),
    "sibling": ("sibling_of", "is_sibling_of"),
    "pet": ("is_pet_of",),
    "dog": ("is_pet_of",),
    "cat": ("is_pet_of",),
}

# Attribution predicates in the KG
_ATTRIBUTION_PREDICATES = {
    "assigned_to",
    "works_on",
    "responsible_for",
    "owns",
    "leads",
    "built",
    "created",
    "finished",
    "completed",
}


# ── Core checker ─────────────────────────────────────────────────────


def _check_attribution(text: str, kg) -> List[Conflict]:
    """Check if an attribution claim conflicts with the KG."""
    conflicts = []
    match = _ATTRIBUTION_PATTERN.search(text)
    if not match:
        return conflicts

    claimed_person = match.group(1).strip()
    claimed_task = match.group(2).strip()

    # Normalize task for comparison
    task_lower = claimed_task.lower().replace(" ", "_").replace("-", "_")

    # Look for any KG triples about this task
    for pred in _ATTRIBUTION_PREDICATES:
        results = kg.query_relationship(pred)
        for fact in results:
            if not fact.get("current", False):
                continue
            fact_obj = fact["object"].lower().replace(" ", "_").replace("-", "_")
            # Check if this fact is about the same task
            if task_lower in fact_obj or fact_obj in task_lower:
                fact_person = fact["subject"]
                if fact_person.lower() != claimed_person.lower():
                    conflicts.append(
                        Conflict(
                            severity="RED",
                            entity=claimed_person,
                            field="attribution",
                            message=(
                                f"attribution conflict — {fact_person} is "
                                f"{pred.replace('_', ' ')} {fact['object']}, "
                                f"not {claimed_person}"
                            ),
                            kg_fact=fact,
                        )
                    )
    return conflicts


def _check_tenure(text: str, kg) -> List[Conflict]:
    """Check if a tenure claim conflicts with KG start dates."""
    conflicts = []
    match = _TENURE_PATTERN.search(text)
    if not match:
        return conflicts

    claimed_person = match.group(1).strip()
    claimed_years = int(match.group(2))

    # Look for employment/joining triples
    results = kg.query_entity(claimed_person, direction="outgoing")
    for fact in results:
        if not fact.get("current", False):
            continue
        pred = fact["predicate"]
        if pred in ("works_at", "joined", "started_at", "employed_by"):
            valid_from = fact.get("valid_from")
            if valid_from:
                try:
                    start_year = int(valid_from[:4])
                    actual_years = date.today().year - start_year
                    if abs(actual_years - claimed_years) >= 1:
                        conflicts.append(
                            Conflict(
                                severity="YELLOW",
                                entity=claimed_person,
                                field="tenure",
                                message=(
                                    f"tenure mismatch — records show "
                                    f"{actual_years} years (started {valid_from}), "
                                    f"not {claimed_years}"
                                ),
                                kg_fact=fact,
                            )
                        )
                except (ValueError, IndexError):
                    pass
    return conflicts


def _check_role(text: str, kg) -> List[Conflict]:
    """Check if a role claim conflicts with KG role facts."""
    conflicts = []
    match = _ROLE_PATTERN.search(text)
    if not match:
        return conflicts

    claimed_person = match.group(1).strip()
    claimed_role = match.group(2).strip().lower()

    results = kg.query_entity(claimed_person, direction="outgoing")
    for fact in results:
        if not fact.get("current", False):
            continue
        if fact["predicate"] in ("has_role", "role", "position", "title"):
            kg_role = fact["object"].lower()
            if kg_role != claimed_role and claimed_role not in kg_role and kg_role not in claimed_role:
                conflicts.append(
                    Conflict(
                        severity="RED",
                        entity=claimed_person,
                        field="role",
                        message=(
                            f"role conflict — records show {fact['object']}, "
                            f"not {claimed_role}"
                        ),
                        kg_fact=fact,
                    )
                )
    return conflicts


def _check_relationship(text: str, kg) -> List[Conflict]:
    """Check if a relationship claim conflicts with KG relationship facts."""
    conflicts = []
    match = _RELATIONSHIP_PATTERN.search(text)
    if not match:
        return conflicts

    person_a = match.group(1).strip()
    person_b = match.group(2).strip()
    claimed_rel = match.group(3).strip().lower()

    expected_predicates = _RELATIONSHIP_PAIRS.get(claimed_rel, ())
    if not expected_predicates:
        return conflicts

    # Check outgoing from person_a
    results_a = kg.query_entity(person_a, direction="both")
    for fact in results_a:
        if not fact.get("current", False):
            continue

        # Is there a relationship between these two people?
        other = fact["object"] if fact["subject"].lower() == person_a.lower() else fact["subject"]
        if other.lower() != person_b.lower():
            continue

        # There IS a relationship — does it match the claimed one?
        if fact["predicate"] not in expected_predicates:
            conflicts.append(
                Conflict(
                    severity="RED",
                    entity=person_a,
                    field="relationship",
                    message=(
                        f"relationship conflict — {person_a} is "
                        f"{fact['predicate'].replace('_', ' ')} {person_b}, "
                        f"not {claimed_rel}"
                    ),
                    kg_fact=fact,
                )
            )
    return conflicts


def _extract_entity_names(text: str) -> List[str]:
    """Extract capitalized names from text (simple heuristic)."""
    # Find capitalized words that aren't at sentence start
    words = text.split()
    names = []
    for i, word in enumerate(words):
        clean = re.sub(r"[^a-zA-Z]", "", word)
        if (
            len(clean) >= 2
            and clean[0].isupper()
            and clean[1:].islower()
            and clean.lower() not in _COMMON_WORDS
        ):
            names.append(clean)
    return list(dict.fromkeys(names))  # dedupe, preserve order


_COMMON_WORDS = {
    "the", "this", "that", "these", "those", "here", "there",
    "has", "have", "had", "was", "were", "been", "being",
    "not", "but", "and", "for", "with", "from", "about",
    "into", "over", "after", "before", "between", "under",
    "again", "further", "then", "once", "also", "just",
    "only", "very", "much", "many", "some", "any", "each",
    "every", "both", "few", "more", "most", "other", "such",
    "than", "too", "very", "can", "will", "should", "would",
    "could", "may", "might", "shall", "must", "need", "now",
    "new", "old", "big", "small", "long", "short", "high",
    "low", "great", "good", "bad", "right", "wrong", "true",
    "false", "yes", "all", "own", "same", "different",
}


# ── Public API ───────────────────────────────────────────────────────


def check_assertion(text: str, kg) -> CheckResult:
    """Check a text assertion against the knowledge graph for contradictions.

    Runs all checkers (attribution, tenure, role, relationship) and
    returns the highest severity found.

    Args:
        text: Natural language assertion to check.
        kg: A KnowledgeGraph instance to query against.

    Returns:
        CheckResult with severity, conflicts, and entities checked.
    """
    all_conflicts = []
    all_conflicts.extend(_check_attribution(text, kg))
    all_conflicts.extend(_check_tenure(text, kg))
    all_conflicts.extend(_check_role(text, kg))
    all_conflicts.extend(_check_relationship(text, kg))

    entities = _extract_entity_names(text)

    # Determine overall severity
    if any(c.severity == "RED" for c in all_conflicts):
        severity = "RED"
    elif any(c.severity == "YELLOW" for c in all_conflicts):
        severity = "YELLOW"
    else:
        severity = "GREEN"

    return CheckResult(
        severity=severity,
        text=text,
        conflicts=all_conflicts,
        entities_checked=entities,
    )
