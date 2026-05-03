"""Knowledge graph backend contract.

Every concrete backend (sqlite, postgres, future remote-RPC) implements this
ABC. The method surface mirrors the historical ``KnowledgeGraph`` class so
existing callers (``mcp_server.py``, ``fact_checker.py``, the seed helper)
work against either backend without code changes.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional


class BaseKnowledgeGraph(ABC):
    """Per-palace temporal entity-relationship graph."""

    # ── Lifecycle ────────────────────────────────────────────────────────

    @abstractmethod
    def close(self) -> None:
        """Release any underlying connection / pool. Idempotent."""

    # ── Writes ───────────────────────────────────────────────────────────

    @abstractmethod
    def add_entity(
        self,
        name: str,
        entity_type: str = "unknown",
        properties: Optional[dict] = None,
    ) -> str:
        """Upsert an entity. Returns the entity id."""

    @abstractmethod
    def add_triple(
        self,
        subject: str,
        predicate: str,
        obj: str,
        valid_from: Optional[str] = None,
        valid_to: Optional[str] = None,
        confidence: float = 1.0,
        source_closet: Optional[str] = None,
        source_file: Optional[str] = None,
        source_drawer_id: Optional[str] = None,
        adapter_name: Optional[str] = None,
    ) -> str:
        """Add a temporal triple. Returns the triple id.

        Auto-creates subject/object entities if missing. Dedupes against
        existing active triples (same subject/predicate/object with
        ``valid_to IS NULL``).
        """

    @abstractmethod
    def invalidate(
        self,
        subject: str,
        predicate: str,
        obj: str,
        ended: Optional[str] = None,
    ) -> None:
        """Set ``valid_to`` on the active triple matching s/p/o."""

    # ── Reads ────────────────────────────────────────────────────────────

    @abstractmethod
    def query_entity(
        self,
        name: str,
        as_of: Optional[str] = None,
        direction: str = "outgoing",
    ) -> list[dict]:
        """Return triples incident to ``name``.

        ``direction`` is ``"outgoing"``, ``"incoming"``, or ``"both"``.
        ``as_of`` filters to facts valid at that ISO date.
        """

    @abstractmethod
    def query_relationship(
        self,
        predicate: str,
        as_of: Optional[str] = None,
    ) -> list[dict]:
        """Return all triples with the given predicate, optionally as-of-filtered."""

    @abstractmethod
    def timeline(self, entity_name: Optional[str] = None) -> list[dict]:
        """Return up to 100 facts in chronological order (NULLS LAST).

        If ``entity_name`` is supplied, scopes to triples touching that entity.
        """

    @abstractmethod
    def stats(self) -> dict:
        """Return ``{entities, triples, current_facts, expired_facts, relationship_types}``."""

    # ── Seeding ──────────────────────────────────────────────────────────

    def seed_from_entity_facts(self, entity_facts: dict) -> None:
        """Bulk-seed from a ``fact_checker.py`` ENTITY_FACTS dict.

        Default implementation is backend-agnostic: it composes ``add_entity``
        and ``add_triple`` calls. Backends are free to override for bulk-load
        performance.
        """
        for key, facts in entity_facts.items():
            name = facts.get("full_name", key.capitalize())
            etype = facts.get("type", "person")
            self.add_entity(
                name,
                etype,
                {
                    "gender": facts.get("gender", ""),
                    "birthday": facts.get("birthday", ""),
                },
            )

            parent = facts.get("parent")
            if parent:
                self.add_triple(
                    name, "child_of", parent.capitalize(), valid_from=facts.get("birthday")
                )

            partner = facts.get("partner")
            if partner:
                self.add_triple(name, "married_to", partner.capitalize())

            relationship = facts.get("relationship", "")
            if relationship == "daughter":
                self.add_triple(
                    name,
                    "is_child_of",
                    facts.get("parent", "").capitalize() or name,
                    valid_from=facts.get("birthday"),
                )
            elif relationship == "husband":
                self.add_triple(name, "is_partner_of", facts.get("partner", name).capitalize())
            elif relationship == "brother":
                self.add_triple(name, "is_sibling_of", facts.get("sibling", name).capitalize())
            elif relationship == "dog":
                self.add_triple(name, "is_pet_of", facts.get("owner", name).capitalize())
                self.add_entity(name, "animal")

            for interest in facts.get("interests", []):
                self.add_triple(name, "loves", interest.capitalize(), valid_from="2025-01-01")

    # ── Helpers ──────────────────────────────────────────────────────────

    @staticmethod
    def entity_id(name: str) -> str:
        """Canonical entity id derived from a display name."""
        return name.lower().replace(" ", "_").replace("'", "")
