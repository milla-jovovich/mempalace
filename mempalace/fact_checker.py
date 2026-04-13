#!/usr/bin/env python3
"""
fact_checker.py — Lightweight contradiction detection for MemPalace.

The original README described contradiction detection as a separate utility.
This module provides that utility in a deliberately explicit form: it checks an
asserted subject/predicate/object triple against the current knowledge graph and
reports whether the new fact is clear, duplicate, or in tension with an
existing current fact.
"""

import argparse
import json
from typing import Optional

from .knowledge_graph import KnowledgeGraph


# These predicates are usually "one current value at a time". When a new object
# appears for one of them, we treat it as a stronger contradiction signal and
# tell the caller to invalidate the old fact first.
SINGLE_VALUE_PREDICATES = frozenset(
    {
        "assigned_to",
        "based_in",
        "birth_date",
        "child_of",
        "due_on",
        "employed_by",
        "husband_of",
        "lives_in",
        "located_in",
        "manager_of",
        "married_to",
        "owner_of",
        "partner_of",
        "reports_to",
        "scheduled_for",
        "wife_of",
        "works_at",
    }
)


def _normalize_predicate(predicate: str) -> str:
    """Match the KG's predicate normalization so checks line up with stored facts."""
    return predicate.lower().replace(" ", "_")


def check_assertion(
    kg: KnowledgeGraph,
    subject: str,
    predicate: str,
    obj: str,
    *,
    as_of: Optional[str] = None,
) -> dict:
    """
    Compare one asserted triple against the graph's current facts.

    The result format is intentionally JSON-friendly because it is used both by
    the standalone utility and by MCP responses.
    """
    normalized_predicate = _normalize_predicate(predicate)
    current_facts = [
        fact
        for fact in kg.query_entity(subject, as_of=as_of, direction="outgoing")
        # When as_of is provided, query_entity() has already time-filtered the
        # facts for that historical slice. In that mode we must keep matches
        # even if they are no longer current today; otherwise historical checks
        # would incorrectly miss expired-but-then-valid facts.
        if fact["predicate"] == normalized_predicate and (as_of is not None or fact["current"])
    ]

    if any(fact["object"] == obj for fact in current_facts):
        return {
            "status": "duplicate",
            "message": "This fact is already present as a current fact.",
            "subject": subject,
            "predicate": normalized_predicate,
            "object": obj,
            "matches": [
                {
                    "object": fact["object"],
                    "valid_from": fact["valid_from"],
                    "valid_to": fact["valid_to"],
                    "source_closet": fact["source_closet"],
                }
                for fact in current_facts
                if fact["object"] == obj
            ],
            "conflicts": [],
        }

    conflicts = [
        {
            "object": fact["object"],
            "valid_from": fact["valid_from"],
            "valid_to": fact["valid_to"],
            "source_closet": fact["source_closet"],
        }
        for fact in current_facts
        if fact["object"] != obj
    ]
    if conflicts:
        is_hard_conflict = normalized_predicate in SINGLE_VALUE_PREDICATES
        return {
            "status": "conflict" if is_hard_conflict else "warning",
            "message": (
                "A different current fact already exists for this relationship. "
                "Invalidate it first if the new fact supersedes the old one."
            ),
            "subject": subject,
            "predicate": normalized_predicate,
            "object": obj,
            "matches": [],
            "conflicts": conflicts,
        }

    return {
        "status": "clear",
        "message": "No conflicting current fact found.",
        "subject": subject,
        "predicate": normalized_predicate,
        "object": obj,
        "matches": [],
        "conflicts": [],
    }


def _build_parser() -> argparse.ArgumentParser:
    """Build a small CLI so the utility is usable outside MCP hosts."""
    parser = argparse.ArgumentParser(description="Check a triple against the MemPalace KG")
    parser.add_argument("subject", help="Assertion subject")
    parser.add_argument("predicate", help="Assertion predicate")
    parser.add_argument("object", help="Assertion object")
    parser.add_argument("--as-of", default=None, help="Optional YYYY-MM-DD date for time-scoped checks")
    parser.add_argument("--kg", default=None, help="Override path to knowledge_graph.sqlite3")
    return parser


def main() -> None:
    """CLI entry point for `python -m mempalace.fact_checker`."""
    args = _build_parser().parse_args()
    kg = KnowledgeGraph(db_path=args.kg)
    result = check_assertion(
        kg,
        args.subject,
        args.predicate,
        args.object,
        as_of=args.as_of,
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
