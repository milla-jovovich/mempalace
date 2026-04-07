#!/usr/bin/env python3
"""
hermes_provider.py — MemPalace as a Hermes Agent memory provider
=================================================================

Implements the hermes-agent MemoryProvider interface so that mempalace
can serve as a pluggable memory backend for hermes-agent.

Drop this file into hermes-agent's plugins/memory/mempalace/ directory
(or use it standalone). It delegates to mempalace's ChromaDB palace and
knowledge graph for storage, search, and recall.

Setup:
  1. pip install mempalace
  2. Copy this file to hermes-agent/plugins/memory/mempalace/__init__.py
  3. Set memory.provider: mempalace in hermes config.yaml

Usage (standalone, without hermes-agent installed):
  from mempalace.hermes_provider import MempalaceProvider

  provider = MempalaceProvider()
  provider.initialize(session_id="session-001")
  context = provider.prefetch("What did we decide about auth?")
  provider.sync_turn("user message", "assistant response")
"""

from __future__ import annotations

import json
import hashlib
import logging
import threading
from datetime import datetime
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Abstract base — inline so this module works without hermes-agent installed
# ---------------------------------------------------------------------------

try:
    from agent.memory_provider import MemoryProvider as _BaseProvider
except ImportError:
    # Standalone mode: define a compatible ABC
    from abc import ABC, abstractmethod

    class _BaseProvider(ABC):
        """Minimal MemoryProvider ABC for standalone use."""

        @property
        @abstractmethod
        def name(self) -> str: ...

        @abstractmethod
        def is_available(self) -> bool: ...

        @abstractmethod
        def initialize(self, session_id: str, **kwargs) -> None: ...

        def system_prompt_block(self) -> str:
            return ""

        def prefetch(self, query: str, *, session_id: str = "") -> str:
            return ""

        def queue_prefetch(self, query: str, *, session_id: str = "") -> None:
            pass

        def sync_turn(self, user_content: str, assistant_content: str, *, session_id: str = "") -> None:
            pass

        @abstractmethod
        def get_tool_schemas(self) -> List[Dict[str, Any]]: ...

        def handle_tool_call(self, tool_name: str, args: Dict[str, Any], **kwargs) -> str:
            raise NotImplementedError

        def shutdown(self) -> None:
            pass

        def on_turn_start(self, turn_number: int, message: str, **kwargs) -> None:
            pass

        def on_session_end(self, messages: List[Dict[str, Any]]) -> None:
            pass

        def on_pre_compress(self, messages: List[Dict[str, Any]]) -> str:
            return ""

        def on_memory_write(self, action: str, target: str, content: str) -> None:
            pass

        def get_config_schema(self) -> List[Dict[str, Any]]:
            return []


class MempalaceProvider(_BaseProvider):
    """MemPalace memory provider for hermes-agent.

    Stores and recalls memories using mempalace's ChromaDB palace,
    AAAK dialect, and temporal knowledge graph.

    Features:
      - Prefetch: semantic search against the palace for each turn
      - Sync: file each exchange into the palace as a drawer
      - Tools: exposes palace search and KG query as hermes tools
      - System prompt: injects Layer 0 (identity) + Layer 1 (essentials)
      - Pre-compress: extracts key facts before context compression
    """

    def __init__(
        self,
        palace_path: str = None,
        collection_name: str = "mempalace_drawers",
        wing: str = "wing_hermes",
        prefetch_limit: int = 3,
        prefetch_min_similarity: float = 0.3,
    ):
        self._palace_path = palace_path
        self._collection_name = collection_name
        self._wing = wing
        self._prefetch_limit = prefetch_limit
        self._prefetch_min_similarity = prefetch_min_similarity
        self._session_id = ""
        self._collection = None
        self._config = None
        self._kg = None
        self._layers = None
        self._prefetch_cache: Dict[str, str] = {}
        self._lock = threading.Lock()

    @property
    def name(self) -> str:
        return "mempalace"

    def is_available(self) -> bool:
        """Check if mempalace is installed and a palace exists."""
        try:
            import chromadb  # noqa: F401
            from mempalace.config import MempalaceConfig
            config = MempalaceConfig()
            import os
            return os.path.isdir(config.palace_path)
        except ImportError:
            return False

    def initialize(self, session_id: str, **kwargs) -> None:
        """Connect to the palace and prepare for recall."""
        self._session_id = session_id

        try:
            import chromadb
            from mempalace.config import MempalaceConfig
            from mempalace.knowledge_graph import KnowledgeGraph

            self._config = MempalaceConfig()
            if self._palace_path:
                self._config.palace_path = self._palace_path

            client = chromadb.PersistentClient(path=self._config.palace_path)
            try:
                self._collection = client.get_collection(self._collection_name)
            except Exception:
                self._collection = client.get_or_create_collection(self._collection_name)

            self._kg = KnowledgeGraph()

            # Try to load layers for system prompt
            try:
                from mempalace.layers import Layer0, Layer1
                self._layers = {
                    "L0": Layer0(),
                    "L1": Layer1(palace_path=self._config.palace_path),
                }
            except Exception:
                self._layers = None

            logger.info("MemPalace provider initialized (palace: %s)", self._config.palace_path)

        except Exception as e:
            logger.warning("MemPalace provider initialization failed: %s", e)

    def system_prompt_block(self) -> str:
        """Inject Layer 0 identity and Layer 1 essentials into the system prompt."""
        if not self._layers:
            return ""

        parts = []
        try:
            l0_text = self._layers["L0"].render()
            if l0_text:
                parts.append(f"[MemPalace Identity]\n{l0_text}")
        except Exception:
            pass

        try:
            l1_text = self._layers["L1"].render()
            if l1_text:
                parts.append(f"[MemPalace Essentials]\n{l1_text}")
        except Exception:
            pass

        if parts:
            parts.append(
                "[MemPalace] Use mempalace_search / mempalace_kg_query tools to "
                "recall specific memories. Never guess — verify."
            )

        return "\n\n".join(parts)

    def prefetch(self, query: str, *, session_id: str = "") -> str:
        """Recall relevant palace memories for the upcoming turn."""
        cache_key = session_id or self._session_id
        cached = self._prefetch_cache.pop(cache_key, "")
        if cached:
            return cached

        # Synchronous fallback if no queued result
        return self._do_search(query)

    def queue_prefetch(self, query: str, *, session_id: str = "") -> None:
        """Queue a background recall for the next turn."""
        cache_key = session_id or self._session_id

        def _bg_search():
            result = self._do_search(query)
            with self._lock:
                self._prefetch_cache[cache_key] = result

        thread = threading.Thread(target=_bg_search, daemon=True)
        thread.start()

    def _do_search(self, query: str) -> str:
        """Search the palace for relevant memories."""
        if not self._collection:
            return ""
        try:
            results = self._collection.query(
                query_texts=[query],
                n_results=self._prefetch_limit,
                include=["documents", "metadatas", "distances"],
            )
            if not results["ids"] or not results["ids"][0]:
                return ""

            parts = []
            for i, doc in enumerate(results["documents"][0]):
                meta = results["metadatas"][0][i]
                dist = results["distances"][0][i]
                similarity = round(1 - dist, 2)
                wing = meta.get("wing", "?")
                room = meta.get("room", "?")
                # Only include if reasonably similar
                if similarity >= self._prefetch_min_similarity:
                    parts.append(f"[{wing}/{room} sim={similarity}] {doc[:500]}")

            return "\n\n".join(parts)
        except Exception as e:
            logger.debug("MemPalace prefetch search failed: %s", e)
            return ""

    def sync_turn(self, user_content: str, assistant_content: str, *, session_id: str = "") -> None:
        """File the exchange into the palace as a drawer."""
        if not self._collection:
            return

        def _bg_sync():
            try:
                # Build content from the exchange
                content = f"Q: {user_content[:1000]}\nA: {assistant_content[:2000]}"
                now = datetime.now()
                drawer_id = (
                    f"hermes_{now.strftime('%Y%m%d_%H%M%S')}_"
                    f"{hashlib.md5(content[:100].encode()).hexdigest()[:8]}"
                )

                self._collection.add(
                    ids=[drawer_id],
                    documents=[content],
                    metadatas=[{
                        "wing": self._wing,
                        "room": "hermes-exchanges",
                        "source_file": f"hermes-session-{session_id or self._session_id}",
                        "added_by": "hermes_provider",
                        "filed_at": now.isoformat(),
                        "type": "exchange",
                    }],
                )
            except Exception as e:
                logger.debug("MemPalace sync_turn failed: %s", e)

        thread = threading.Thread(target=_bg_sync, daemon=True)
        thread.start()

    def get_tool_schemas(self) -> List[Dict[str, Any]]:
        """Expose palace search and KG query as hermes tools."""
        return [
            {
                "name": "mempalace_search",
                "description": (
                    "Search the MemPalace for relevant memories. Returns verbatim "
                    "drawer content with similarity scores."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "What to search for",
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Max results (default 5)",
                        },
                        "wing": {
                            "type": "string",
                            "description": "Filter by wing (optional)",
                        },
                    },
                    "required": ["query"],
                },
            },
            {
                "name": "mempalace_kg_query",
                "description": (
                    "Query the MemPalace knowledge graph for an entity's relationships. "
                    "Returns typed facts with temporal validity."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "entity": {
                            "type": "string",
                            "description": "Entity to query (e.g. 'Max', 'MyProject')",
                        },
                    },
                    "required": ["entity"],
                },
            },
        ]

    def handle_tool_call(self, tool_name: str, args: Dict[str, Any], **kwargs) -> str:
        """Handle tool calls from hermes-agent."""
        if tool_name == "mempalace_search":
            return self._handle_search(args)
        elif tool_name == "mempalace_kg_query":
            return self._handle_kg_query(args)
        return json.dumps({"error": f"Unknown tool: {tool_name}"})

    def _handle_search(self, args: Dict[str, Any]) -> str:
        """Handle mempalace_search tool call."""
        query = args.get("query", "")
        limit = args.get("limit", 5)
        wing = args.get("wing")

        if not self._collection:
            return json.dumps({"error": "Palace not initialized"})

        try:
            kwargs = {
                "query_texts": [query],
                "n_results": limit,
                "include": ["documents", "metadatas", "distances"],
            }
            if wing:
                kwargs["where"] = {"wing": wing}

            results = self._collection.query(**kwargs)
            hits = []
            if results["ids"] and results["ids"][0]:
                for i, doc in enumerate(results["documents"][0]):
                    meta = results["metadatas"][0][i]
                    dist = results["distances"][0][i]
                    hits.append({
                        "content": doc,
                        "wing": meta.get("wing", "?"),
                        "room": meta.get("room", "?"),
                        "similarity": round(1 - dist, 3),
                    })
            return json.dumps({"results": hits, "count": len(hits)})
        except Exception as e:
            return json.dumps({"error": str(e)})

    def _handle_kg_query(self, args: Dict[str, Any]) -> str:
        """Handle mempalace_kg_query tool call."""
        entity = args.get("entity", "")
        if not self._kg:
            return json.dumps({"error": "Knowledge graph not initialized"})
        try:
            facts = self._kg.query_entity(entity)
            return json.dumps({"entity": entity, "facts": facts, "count": len(facts)})
        except Exception as e:
            return json.dumps({"error": str(e)})

    def on_pre_compress(self, messages: List[Dict[str, Any]]) -> str:
        """Extract key facts before context compression discards old messages."""
        # Extract entities mentioned in the messages about to be compressed
        entities_mentioned = set()
        for msg in messages:
            content = msg.get("content", "")
            if isinstance(content, str) and len(content) > 20:
                # Simple entity detection: capitalized words that appear multiple times
                import re
                words = re.findall(r'\b[A-Z][a-z]{2,}\b', content)
                entities_mentioned.update(words)

        if not entities_mentioned or not self._kg:
            return ""

        # Query KG for any mentioned entities
        facts = []
        for entity in list(entities_mentioned)[:5]:  # Limit to top 5
            try:
                entity_facts = self._kg.query_entity(entity)
                if entity_facts:
                    facts.extend(entity_facts[:3])
            except Exception:
                pass

        if not facts:
            return ""

        return (
            "[MemPalace context preservation] The following facts from the "
            "knowledge graph are relevant to the conversation being compressed:\n"
            + "\n".join(f"- {f}" for f in facts[:10])
        )

    def on_session_end(self, messages: List[Dict[str, Any]]) -> None:
        """Extract and store key facts at session end."""
        if not self._kg or not messages:
            return

        # Simple extraction: look for decisions and milestones
        try:
            from mempalace.general_extractor import extract_memories
            full_text = "\n".join(
                msg.get("content", "") for msg in messages
                if isinstance(msg.get("content"), str)
            )
            if len(full_text) > 100:
                memories = extract_memories(full_text)
                # Store top decisions/milestones to KG
                for mem in memories[:5]:
                    if mem.get("memory_type") in ("decision", "milestone"):
                        self._kg.add_triple(
                            "hermes_session",
                            mem["memory_type"],
                            mem["content"][:200],
                            valid_from=datetime.now().strftime("%Y-%m-%d"),
                        )
        except Exception as e:
            logger.debug("MemPalace on_session_end extraction failed: %s", e)

    def on_memory_write(self, action: str, target: str, content: str) -> None:
        """Mirror hermes built-in memory writes to the palace."""
        if not self._collection or not content:
            return
        try:
            if action == "add":
                now = datetime.now()
                drawer_id = (
                    f"hermes_mem_{now.strftime('%Y%m%d_%H%M%S')}_"
                    f"{hashlib.md5(content[:50].encode()).hexdigest()[:8]}"
                )
                self._collection.add(
                    ids=[drawer_id],
                    documents=[content],
                    metadatas=[{
                        "wing": self._wing,
                        "room": f"hermes-{target}",
                        "source_file": f"hermes-{target}",
                        "added_by": "hermes_builtin_mirror",
                        "filed_at": now.isoformat(),
                        "type": f"memory_{target}",
                    }],
                )
        except Exception as e:
            logger.debug("MemPalace on_memory_write failed: %s", e)

    def shutdown(self) -> None:
        """Clean shutdown."""
        self._prefetch_cache.clear()
        logger.info("MemPalace provider shut down")


# ---------------------------------------------------------------------------
# Plugin registration (for hermes-agent plugin discovery)
# ---------------------------------------------------------------------------

def register(ctx):
    """Register MempalaceProvider with hermes-agent's plugin system."""
    ctx.register_memory_provider(MempalaceProvider())
