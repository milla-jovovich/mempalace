#!/usr/bin/env python3
"""
MemPalace MCP Server — read/write palace access for Claude Code
================================================================
Install: claude mcp add mempalace -- python -m mempalace.mcp_server [--palace /path/to/palace]

Tools (read):
  mempalace_status          — total drawers, wing/room breakdown
  mempalace_list_wings      — all wings with drawer counts
  mempalace_list_rooms      — rooms within a wing
  mempalace_get_taxonomy    — full wing → room → count tree
  mempalace_search          — semantic search, optional wing/room filter
  mempalace_check_duplicate — check if content already exists before filing

Tools (write):
  mempalace_add_drawer      — file verbatim content into a wing/room
  mempalace_delete_drawer   — remove a drawer by ID
"""

import argparse
import os
import sys
import json
import logging
import hashlib
from datetime import datetime
from pathlib import Path

from .config import MempalaceConfig, sanitize_name, sanitize_content
from .version import __version__
from .query_sanitizer import sanitize_query
from .searcher import search_memories
from .palace_graph import traverse, find_tunnels, graph_stats
import chromadb

from .knowledge_graph import KnowledgeGraph

logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stderr)
logger = logging.getLogger("mempalace_mcp")


def _parse_args():
    parser = argparse.ArgumentParser(description="MemPalace MCP Server")
    parser.add_argument(
        "--palace",
        metavar="PATH",
        help="Path to the palace directory (overrides config file and env var)",
    )
    args, unknown = parser.parse_known_args()
    if unknown:
        logger.debug("Ignoring unknown args: %s", unknown)
    return args


_args = _parse_args()

if _args.palace:
    os.environ["MEMPALACE_PALACE_PATH"] = os.path.abspath(_args.palace)

_config = MempalaceConfig()
if _args.palace:
    _kg = KnowledgeGraph(db_path=os.path.join(_config.palace_path, "knowledge_graph.sqlite3"))
else:
    _kg = KnowledgeGraph()


_client_cache = None
_collection_cache = None


# ==================== WRITE-AHEAD LOG ====================
# Every write operation is logged to a JSONL file before execution.
# This provides an audit trail for detecting memory poisoning and
# enables review/rollback of writes from external or untrusted sources.

_WAL_DIR = Path(os.path.expanduser("~/.mempalace/wal"))
_WAL_DIR.mkdir(parents=True, exist_ok=True)
try:
    _WAL_DIR.chmod(0o700)
except (OSError, NotImplementedError):
    pass
_WAL_FILE = _WAL_DIR / "write_log.jsonl"


def _wal_log(operation: str, params: dict, result: dict = None):
    """Append a write operation to the write-ahead log."""
    entry = {
        "timestamp": datetime.now().isoformat(),
        "operation": operation,
        "params": params,
        "result": result,
    }
    try:
        with open(_WAL_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, default=str) + "\n")
        try:
            _WAL_FILE.chmod(0o600)
        except (OSError, NotImplementedError):
            pass
    except Exception as e:
        logger.error(f"WAL write failed: {e}")


_client_cache = None
_collection_cache = None


def _get_client():
    """Return a singleton ChromaDB PersistentClient."""
    global _client_cache
    if _client_cache is None:
        _client_cache = chromadb.PersistentClient(path=_config.palace_path)
    return _client_cache


def _get_collection(create=False):
    """Return the ChromaDB collection, caching the client between calls."""
    global _collection_cache
    try:
        client = _get_client()
        if create:
            _collection_cache = client.get_or_create_collection(_config.collection_name)
        elif _collection_cache is None:
            _collection_cache = client.get_collection(_config.collection_name)
        return _collection_cache
    except Exception:
        return None


def _no_palace():
    return {
        "error": "No palace found",
        "hint": "Run: mempalace init <dir> && mempalace mine <dir>",
    }


# ==================== READ TOOLS ====================


def tool_status():
    col = _get_collection()
    if not col:
        return _no_palace()
    count = col.count()
    wings = {}
    rooms = {}
    batch_size = 5000
    offset = 0
    error_info = None
    while True:
        try:
            batch = col.get(include=["metadatas"], limit=batch_size, offset=offset)
            rows = batch["metadatas"]
            for m in rows:
                w = m.get("wing", "unknown")
                r = m.get("room", "unknown")
                wings[w] = wings.get(w, 0) + 1
                rooms[r] = rooms.get(r, 0) + 1
            offset += len(rows)
            if len(rows) < batch_size:
                break
        except Exception as e:
            error_info = f"Partial result, failed at offset {offset}: {str(e)}"
            break
    result = {
        "total_drawers": count,
        "wings": wings,
        "rooms": rooms,
        "palace_path": _config.palace_path,
        "protocol": PALACE_PROTOCOL,
        "aaak_dialect": AAAK_SPEC,
    }
    if error_info:
        result["error"] = error_info
        result["partial"] = True
    return result


# ── AAAK Dialect Spec ─────────────────────────────────────────────────────────
# Included in status response so the AI learns it on first wake-up call.
# Also available via mempalace_get_aaak_spec tool.

PALACE_PROTOCOL = """IMPORTANT — MemPalace Memory Protocol:
1. ON WAKE-UP: Call mempalace_status to load palace overview + AAAK spec.
2. BEFORE RESPONDING about any person, project, or past event: call mempalace_kg_query or mempalace_search FIRST. Never guess — verify.
3. IF UNSURE about a fact (name, gender, age, relationship): say "let me check" and query the palace. Wrong is worse than slow.
4. AFTER EACH SESSION: call mempalace_diary_write to record what happened, what you learned, what matters.
5. WHEN FACTS CHANGE: call mempalace_kg_invalidate on the old fact, mempalace_kg_add for the new one.

This protocol ensures the AI KNOWS before it speaks. Storage is not memory — but storage + this protocol = memory."""

AAAK_SPEC = """AAAK is a compressed memory dialect that MemPalace uses for efficient storage.
It is designed to be readable by both humans and LLMs without decoding.

FORMAT:
  ENTITIES: 3-letter uppercase codes. ALC=Alice, JOR=Jordan, RIL=Riley, MAX=Max, BEN=Ben.
  EMOTIONS: *action markers* before/during text. *warm*=joy, *fierce*=determined, *raw*=vulnerable, *bloom*=tenderness.
  STRUCTURE: Pipe-separated fields. FAM: family | PROJ: projects | ⚠: warnings/reminders.
  DATES: ISO format (2026-03-31). COUNTS: Nx = N mentions (e.g., 570x).
  IMPORTANCE: ★ to ★★★★★ (1-5 scale).
  HALLS: hall_facts, hall_events, hall_discoveries, hall_preferences, hall_advice.
  WINGS: wing_user, wing_agent, wing_team, wing_code, wing_myproject, wing_hardware, wing_ue5, wing_ai_research.
  ROOMS: Hyphenated slugs representing named ideas (e.g., chromadb-setup, gpu-pricing).

EXAMPLE:
  FAM: ALC→♡JOR | 2D(kids): RIL(18,sports) MAX(11,chess+swimming) | BEN(contributor)

Read AAAK naturally — expand codes mentally, treat *markers* as emotional context.
When WRITING AAAK: use entity codes, mark emotions, keep structure tight."""


def tool_list_wings():
    col = _get_collection()
    if not col:
        return _no_palace()
    wings = {}
    batch_size = 5000
    offset = 0
    try:
        col.count()  # verify collection is accessible
    except Exception as e:
        return {"wings": {}, "error": str(e)}
    while True:
        try:
            batch = col.get(include=["metadatas"], limit=batch_size, offset=offset)
            rows = batch["metadatas"]
            for m in rows:
                w = m.get("wing", "unknown")
                wings[w] = wings.get(w, 0) + 1
            offset += len(rows)
            if len(rows) < batch_size:
                break
        except Exception as e:
            return {
                "wings": wings,
                "error": f"Partial result, failed at offset {offset}: {str(e)}",
                "partial": True,
            }
    return {"wings": wings}


def tool_list_rooms(wing: str = None):
    col = _get_collection()
    if not col:
        return _no_palace()
    rooms = {}
    batch_size = 5000
    offset = 0
    where = {"wing": wing} if wing else None
    try:
        col.count()  # verify collection is accessible
    except Exception as e:
        return {"wing": wing or "all", "rooms": {}, "error": str(e)}
    while True:
        try:
            kwargs = {"include": ["metadatas"], "limit": batch_size, "offset": offset}
            if where:
                kwargs["where"] = where
            batch = col.get(**kwargs)
            rows = batch["metadatas"]
            for m in rows:
                r = m.get("room", "unknown")
                rooms[r] = rooms.get(r, 0) + 1
            offset += len(rows)
            if len(rows) < batch_size:
                break
        except Exception as e:
            return {
                "wing": wing or "all",
                "rooms": rooms,
                "error": f"Partial result, failed at offset {offset}: {str(e)}",
                "partial": True,
            }
    return {"wing": wing or "all", "rooms": rooms}


def tool_get_taxonomy():
    col = _get_collection()
    if not col:
        return _no_palace()
    taxonomy = {}
    batch_size = 5000
    offset = 0
    try:
        col.count()  # verify collection is accessible
    except Exception as e:
        return {"taxonomy": {}, "error": str(e)}
    while True:
        try:
            batch = col.get(include=["metadatas"], limit=batch_size, offset=offset)
            rows = batch["metadatas"]
            for m in rows:
                w = m.get("wing", "unknown")
                r = m.get("room", "unknown")
                if w not in taxonomy:
                    taxonomy[w] = {}
                taxonomy[w][r] = taxonomy[w].get(r, 0) + 1
            offset += len(rows)
            if len(rows) < batch_size:
                break
        except Exception as e:
            return {
                "taxonomy": taxonomy,
                "error": f"Partial result, failed at offset {offset}: {str(e)}",
                "partial": True,
            }
    return {"taxonomy": taxonomy}


def _hybrid_score(similarity: float, importance: float, date_added_iso: str) -> float:
    """Hybrid ranking score for search results.

    Combines semantic similarity with importance tier and time-decay:

        hybrid = similarity + (importance - 3) * 0.1 - log10(age_days + 1) * 0.02

    Properties:
        - Similarity dominates the shape of results (no weak-but-critical drawer
          beats a strong semantic match on a default-importance drawer)
        - Importance nudges critical drawers up: a 5% similarity deficit can be
          overcome by an importance=5 vs importance=3 gap
        - Log-decay gently demotes old content (0.02 weight means 1 year old
          costs ~0.05 points vs 1 day old)
        - Within a tight similarity band, high-importance recent drawers surface first
    """
    import math

    try:
        sim = float(similarity or 0.0)
    except (TypeError, ValueError):
        sim = 0.0
    try:
        imp = float(importance or 3.0)
    except (TypeError, ValueError):
        imp = 3.0

    # Age from date_added (fall back to large age if unknown)
    dt = _parse_iso_datetime_safe(date_added_iso)
    if dt is None:
        age_days = 365.0
    else:
        now = datetime.now(dt.tzinfo) if dt.tzinfo else datetime.now()
        age_seconds = max(0.0, (now - dt).total_seconds())
        age_days = age_seconds / 86400.0

    return sim + (imp - 3.0) * 0.1 - math.log10(age_days + 1.0) * 0.02


def _parse_iso_datetime_safe(value):
    """Parse ISO-format datetime (mcp_server local helper, mirrors layers._parse_iso_datetime)."""
    if not value or not isinstance(value, str):
        return None
    try:
        from datetime import timezone
        s = value.strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (TypeError, ValueError):
        return None


def tool_search(
    query: str,
    limit: int = 5,
    wing: str = None,
    room: str = None,
    context: str = None,
    sort_by: str = "hybrid",
):
    """Search palace drawers with hybrid importance-decay-aware ranking by default.

    sort_by:
        "hybrid" (DEFAULT) — similarity + importance bonus + time-decay penalty.
                             Semantically-matching drawers dominate, but importance
                             and recency break ties. This is what you want for
                             almost every query.
        "similarity"       — pure ChromaDB vector similarity (legacy behavior).
                             Use when you want raw semantic match with no
                             importance/recency influence.
        "score"            — pure Layer1 decay-aware importance ranking
                             (importance*10 - log10(age+1)*0.5). Ignores similarity.
                             Use for wing-browse "what's critical in X" queries.
        "importance"       — pure importance DESC, ties by recency. Admin view.
        "date"             — chronological, most recent first. Diary reads.

    All non-similarity modes fetch ~limit*5 candidates via similarity first,
    then re-rank client-side. For pure metadata-based queries (no semantic
    intent at all), pass query='' to skip similarity and sort the whole
    filtered set.
    """
    from .layers import compute_decay_score

    # Mitigate system prompt contamination (Issue #333)
    sanitized = sanitize_query(query)

    # Determine fetch size: re-ranking modes need more candidates
    needs_rerank = sort_by != "similarity"
    fetch_limit = max(limit * 5, 50) if needs_rerank else limit

    result = search_memories(
        sanitized["clean_query"],
        palace_path=_config.palace_path,
        wing=wing,
        room=room,
        n_results=fetch_limit,
    )

    # Re-rank if requested (always when sort_by != "similarity", including default "hybrid")
    if needs_rerank and isinstance(result, dict) and result.get("results"):
        items = result["results"]

        def _importance(item):
            meta = item.get("metadata") or {}
            try:
                return float(meta.get("importance", 3))
            except (TypeError, ValueError):
                return 3.0

        def _date(item):
            meta = item.get("metadata") or {}
            return meta.get("date_added") or meta.get("filed_at") or ""

        def _similarity(item):
            try:
                return float(item.get("similarity") or 0.0)
            except (TypeError, ValueError):
                return 0.0

        if sort_by == "hybrid":
            items.sort(
                key=lambda x: _hybrid_score(_similarity(x), _importance(x), _date(x)),
                reverse=True,
            )
        elif sort_by == "score":
            items.sort(key=lambda x: compute_decay_score(_importance(x), _date(x)), reverse=True)
        elif sort_by == "importance":
            items.sort(key=lambda x: (_importance(x), _date(x)), reverse=True)
        elif sort_by == "date":
            items.sort(key=lambda x: _date(x), reverse=True)
        else:
            return {
                "error": (
                    f"sort_by '{sort_by}' not supported. "
                    f"Use: hybrid (default), similarity, score, importance, date."
                )
            }

        result["results"] = items[:limit]
        result["sort_by"] = sort_by
        result["reranked"] = True

    # Attach sanitizer metadata for transparency
    if sanitized["was_sanitized"]:
        result["query_sanitized"] = True
        result["sanitizer"] = {
            "method": sanitized["method"],
            "original_length": sanitized["original_length"],
            "clean_length": sanitized["clean_length"],
            "clean_query": sanitized["clean_query"],
        }
    if context:
        result["context_received"] = True
    return result


def tool_check_duplicate(content: str, threshold: float = 0.9):
    col = _get_collection()
    if not col:
        return _no_palace()
    try:
        results = col.query(
            query_texts=[content],
            n_results=5,
            include=["metadatas", "documents", "distances"],
        )
        duplicates = []
        if results["ids"] and results["ids"][0]:
            for i, drawer_id in enumerate(results["ids"][0]):
                dist = results["distances"][0][i]
                similarity = round(1 - dist, 3)
                if similarity >= threshold:
                    meta = results["metadatas"][0][i]
                    doc = results["documents"][0][i]
                    duplicates.append(
                        {
                            "id": drawer_id,
                            "wing": meta.get("wing", "?"),
                            "room": meta.get("room", "?"),
                            "similarity": similarity,
                            "content": doc[:200] + "..." if len(doc) > 200 else doc,
                        }
                    )
        return {
            "is_duplicate": len(duplicates) > 0,
            "matches": duplicates,
        }
    except Exception as e:
        return {"error": str(e)}


def tool_get_aaak_spec():
    """Return the AAAK dialect specification."""
    return {"aaak_spec": AAAK_SPEC}


def tool_traverse_graph(start_room: str, max_hops: int = 2):
    """Walk the palace graph from a room. Find connected ideas across wings."""
    col = _get_collection()
    if not col:
        return _no_palace()
    return traverse(start_room, col=col, max_hops=max_hops)


def tool_find_tunnels(wing_a: str = None, wing_b: str = None):
    """Find rooms that bridge two wings — the hallways connecting domains."""
    col = _get_collection()
    if not col:
        return _no_palace()
    return find_tunnels(wing_a, wing_b, col=col)


def tool_graph_stats():
    """Palace graph overview: nodes, tunnels, edges, connectivity."""
    col = _get_collection()
    if not col:
        return _no_palace()
    return graph_stats(col=col)


# ==================== WRITE TOOLS ====================


VALID_HALLS = {
    "hall_facts",
    "hall_events",
    "hall_discoveries",
    "hall_preferences",
    "hall_advice",
    "hall_diary",
}


def _validate_importance(importance):
    """Coerce and validate an importance value (1-5). Returns int or raises ValueError."""
    if importance is None:
        return None
    try:
        n = int(importance)
    except (TypeError, ValueError):
        raise ValueError(
            f"importance must be an integer 1-5 (got {importance!r}). "
            f"Importance scale: 5=critical, 4=canonical, 3=default, 2=low, 1=junk."
        )
    if n < 1 or n > 5:
        raise ValueError(
            f"importance must be between 1 and 5 (got {n}). "
            f"Importance scale: 5=critical unmissable, 4=canonical rules/cookbooks, "
            f"3=historical events (default), 2=low priority, 1=junk/quarantine."
        )
    return n


VALID_KINDS = {
    "entity",      # a concrete individual thing
    "predicate",   # a relationship type
    "class",       # a category/domain-type definition
    "literal",     # a raw value (string, integer, timestamp, URL, path)
}

def _validate_kind(kind):
    """Validate entity kind (ontological role). REQUIRED — no default."""
    if kind is None:
        raise ValueError(
            "kind is REQUIRED. Must be one of: 'entity' (concrete thing), "
            "'predicate' (relationship type), 'class' (category definition), "
            "'literal' (raw value). You must explicitly choose the ontological role."
        )
    if kind not in VALID_KINDS:
        raise ValueError(
            f"kind must be one of {sorted(VALID_KINDS)} (got {kind!r}). "
            f"entity=concrete thing (default), predicate=relationship type, "
            f"class=category/type definition, literal=raw value. "
            f"Domain types (system, person, project, etc.) are NOT kinds — "
            f"they are class-kind entities linked via is_a edges."
        )
    return kind


def _validate_hall(hall):
    """Validate a hall value. Returns string or raises ValueError."""
    if hall is None:
        return None
    if hall not in VALID_HALLS:
        raise ValueError(
            f"hall must be one of {sorted(VALID_HALLS)} (got {hall!r}). "
            f"hall_facts=stable truths, hall_events=things that happened, "
            f"hall_discoveries=lessons learned, hall_preferences=user rules, "
            f"hall_advice=how-to guides, hall_diary=chronological journal."
        )
    return hall


def tool_add_drawer(
    wing: str,
    room: str,
    content: str,
    source_file: str = None,
    added_by: str = "mcp",
    hall: str = None,
    importance: int = None,
    entity: str = None,
):
    """File verbatim content into a wing/room. Checks for duplicates first.

    ALL classification params are REQUIRED (no lazy defaults):
        hall: content type — REQUIRED. One of hall_facts, hall_events,
              hall_discoveries, hall_preferences, hall_advice, hall_diary.
        importance: integer 1-5 — REQUIRED. 5=critical, 4=canonical,
                    3=default, 2=low, 1=junk.
        entity: entity name (or comma-separated list) — REQUIRED. Links this drawer to
                via has_memory edges in the KG. If not provided, defaults to the
                wing name as entity. This prevents orphan drawers — every drawer
                should be discoverable via the entity graph.

    Note: date_added is always set to the current time. Diary drawers
    (via diary_write) are exempt from the entity requirement.
    """
    try:
        wing = sanitize_name(wing, "wing")
        room = sanitize_name(room, "room")
        content = sanitize_content(content)
        hall = _validate_hall(hall)
        importance = _validate_importance(importance)
    except ValueError as e:
        return {"success": False, "error": str(e)}

    col = _get_collection(create=True)
    if not col:
        return _no_palace()

    drawer_id = f"drawer_{wing}_{room}_{hashlib.sha256((wing + room + content[:100]).encode()).hexdigest()[:24]}"

    _wal_log(
        "add_drawer",
        {
            "drawer_id": drawer_id,
            "wing": wing,
            "room": room,
            "added_by": added_by,
            "content_length": len(content),
            "content_preview": content[:200],
            "hall": hall,
            "importance": importance,
        },
    )

    # Idempotency: if the deterministic ID already exists, return success as a no-op.
    try:
        existing = col.get(ids=[drawer_id])
        if existing and existing["ids"]:
            return {"success": True, "reason": "already_exists", "drawer_id": drawer_id}
    except Exception:
        pass

    now_iso = datetime.now().isoformat()
    meta = {
        "wing": wing,
        "room": room,
        "source_file": source_file or "",
        "chunk_index": 0,
        "added_by": added_by,
        "filed_at": now_iso,
        "date_added": now_iso,
    }
    if hall is not None:
        meta["hall"] = hall
    if importance is not None:
        meta["importance"] = importance

    try:
        col.upsert(
            ids=[drawer_id],
            documents=[content],
            metadatas=[meta],
        )
        logger.info(f"Filed drawer: {drawer_id} -> {wing}/{room} hall={hall} imp={importance}")

        # Create has_memory entity link(s)
        linked_entities = []
        entity_names = []
        if entity:
            # Support comma-separated list
            entity_names = [e.strip() for e in entity.split(",") if e.strip()]
        else:
            # Default: link to wing name as entity
            entity_names = [wing]

        from .knowledge_graph import normalize_entity_name
        for ename in entity_names:
            eid = normalize_entity_name(ename)
            # Auto-create entity if it doesn't exist (soft — drawer linking shouldn't fail)
            existing_entity = _kg.get_entity(eid)
            if not existing_entity:
                _kg.add_entity(ename, kind="entity", description=f"Auto-created from drawer link in {wing}/{room}")
            try:
                _kg.add_triple(eid, "has_memory", drawer_id)
                linked_entities.append(eid)
            except Exception:
                pass  # Non-fatal: drawer exists, linking failed

        return {
            "success": True,
            "drawer_id": drawer_id,
            "wing": wing,
            "room": room,
            "hall": hall,
            "importance": importance,
            "linked_entities": linked_entities,
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def tool_delete_drawer(drawer_id: str):
    """Delete a single drawer by ID."""
    col = _get_collection()
    if not col:
        return _no_palace()
    existing = col.get(ids=[drawer_id])
    if not existing["ids"]:
        return {"success": False, "error": f"Drawer not found: {drawer_id}"}

    # Log the deletion with the content being removed for audit trail
    deleted_content = existing.get("documents", [""])[0] if existing.get("documents") else ""
    deleted_meta = existing.get("metadatas", [{}])[0] if existing.get("metadatas") else {}
    _wal_log(
        "delete_drawer",
        {
            "drawer_id": drawer_id,
            "deleted_meta": deleted_meta,
            "content_preview": deleted_content[:200],
        },
    )

    try:
        col.delete(ids=[drawer_id])
        logger.info(f"Deleted drawer: {drawer_id}")
        return {"success": True, "drawer_id": drawer_id}
    except Exception as e:
        return {"success": False, "error": str(e)}


def tool_wake_up(wing: str = None):
    """Return L0 (identity) + L1 (importance-ranked essential story) wake-up text.

    Loads:
    - L0 from ~/.mempalace/identity.txt (user-authored, ~100 tokens)
    - L1 from top-importance drawers in the palace (~500-800 tokens)

    If a wing is provided, L1 is scoped to that wing — useful for
    project/agent-focused boot contexts (e.g., wing="ga" loads only
    GA-private drawers, wing="wing_pfe" loads only PFE's content).

    Total return: ~600-900 tokens. Inject into the session's system prompt
    or first message at wake-up. Replaces hand-rolled mempalace_search chains.

    Ranking in L1 is importance-weighted with time decay — see the
    retrieval-semantics rules drawer for the formula.
    """
    try:
        from .layers import MemoryStack
    except Exception as e:
        return {"success": False, "error": f"layers module unavailable: {e}"}

    try:
        stack = MemoryStack()
        text = stack.wake_up(wing=wing)
        token_estimate = len(text) // 4

        # ── Auto-declare predicates, classes, and top entities ──
        auto_declared = {"predicates": [], "classes": [], "entities": []}

        # 1. Auto-declare ALL canonical predicates (kind=predicate)
        predicates = _kg.list_entities(status="active", kind="predicate")
        for p in predicates:
            _declared_entities.add(p["id"])
            auto_declared["predicates"].append({"id": p["id"], "description": p["description"][:100]})

        # 2. Auto-declare ALL domain type classes (kind=class)
        classes = _kg.list_entities(status="active", kind="class")
        for c in classes:
            _declared_entities.add(c["id"])
            auto_declared["classes"].append({"id": c["id"], "description": c["description"][:100]})

        # 3. Auto-declare top entities for this wing (by importance+decay)
        if wing:
            # Get entities that have has_memory edges to drawers in this wing
            # For now: list all active entities of kind=entity, sorted by importance
            entities = _kg.list_entities(status="active", kind="entity")
            # Take top 20 by importance (decay scoring would need date, defer for now)
            top_entities = entities[:20]
            for e in top_entities:
                _declared_entities.add(e["id"])
                auto_declared["entities"].append({
                    "id": e["id"],
                    "description": e["description"][:100],
                    "importance": e["importance"],
                })

        return {
            "success": True,
            "wing": wing,
            "text": text,
            "estimated_tokens": token_estimate,
            "auto_declared": auto_declared,
            "total_declared": len(_declared_entities),
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def tool_update_drawer_metadata(
    drawer_id: str,
    wing: str = None,
    room: str = None,
    hall: str = None,
    importance: int = None,
):
    """Update metadata fields on an existing drawer in place.

    Preserves embeddings (no re-vectorization) — faster than delete+recreate
    for wing/room migrations and retroactive hall/importance tagging.

    Any param left as None preserves the existing value. Use this for:
    - Retroactive hall classification on legacy drawers
    - Bumping importance when a drawer turns out to be more critical
    - Moving drawers between wings/rooms without re-embedding

    Note: cannot change the drawer_id or content. For those, use delete + add.
    """
    try:
        if wing is not None:
            wing = sanitize_name(wing, "wing")
        if room is not None:
            room = sanitize_name(room, "room")
        hall = _validate_hall(hall)
        importance = _validate_importance(importance)
    except ValueError as e:
        return {"success": False, "error": str(e)}

    col = _get_collection()
    if not col:
        return _no_palace()

    existing = col.get(ids=[drawer_id], include=["metadatas"])
    if not existing["ids"]:
        return {"success": False, "error": f"Drawer not found: {drawer_id}"}

    old_meta = dict(existing["metadatas"][0])
    new_meta = dict(old_meta)
    updated_fields = []
    if wing is not None and old_meta.get("wing") != wing:
        new_meta["wing"] = wing
        updated_fields.append("wing")
    if room is not None and old_meta.get("room") != room:
        new_meta["room"] = room
        updated_fields.append("room")
    if hall is not None and old_meta.get("hall") != hall:
        new_meta["hall"] = hall
        updated_fields.append("hall")
    if importance is not None and old_meta.get("importance") != importance:
        new_meta["importance"] = importance
        updated_fields.append("importance")

    if not updated_fields:
        return {
            "success": True,
            "reason": "no_change",
            "drawer_id": drawer_id,
        }

    _wal_log(
        "update_drawer_metadata",
        {
            "drawer_id": drawer_id,
            "old_meta": old_meta,
            "new_meta": new_meta,
            "updated_fields": updated_fields,
        },
    )

    try:
        col.update(ids=[drawer_id], metadatas=[new_meta])
        logger.info(f"Updated drawer metadata: {drawer_id} fields={updated_fields}")
        return {
            "success": True,
            "drawer_id": drawer_id,
            "updated_fields": updated_fields,
            "new_metadata": new_meta,
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


# ==================== KNOWLEDGE GRAPH ====================


def tool_kg_query(entity: str, as_of: str = None, direction: str = "both"):
    """Query the knowledge graph for an entity's relationships."""
    results = _kg.query_entity(entity, as_of=as_of, direction=direction)
    return {"entity": entity, "as_of": as_of, "facts": results, "count": len(results)}


def tool_kg_add(
    subject: str, predicate: str, object: str, valid_from: str = None, source_closet: str = None
):
    """Add a relationship to the knowledge graph.

    IMPORTANT: All three parts must be declared in this session:
    - subject: declared entity (any type EXCEPT predicate)
    - predicate: declared entity with type="predicate"
    - object: declared entity (any type EXCEPT predicate)

    Call kg_declare_entity for subject/object entities, and
    kg_declare_entity with kind="predicate" for predicates.
    """
    from .knowledge_graph import normalize_entity_name

    try:
        subject = sanitize_name(subject, "subject")
        predicate = sanitize_name(predicate, "predicate")
        object = sanitize_name(object, "object")
    except ValueError as e:
        return {"success": False, "error": str(e)}

    # Enforce entity declaration: subject, predicate, and object must all be declared
    sub_normalized = normalize_entity_name(subject)
    pred_normalized = normalize_entity_name(predicate)
    obj_normalized = normalize_entity_name(object)

    errors = []

    # Check subject (must be declared, must NOT be a predicate)
    if sub_normalized not in _declared_entities:
        errors.append(
            f"subject '{sub_normalized}' not declared. Call: "
            f"kg_declare_entity(name='{subject}', description='...', kind='entity')"
        )
    else:
        sub_entity = _kg.get_entity(sub_normalized)
        if sub_entity and sub_entity.get("kind") == "predicate":
            errors.append(
                f"subject '{sub_normalized}' is kind=predicate, not an entity. "
                f"Subjects must be kind=entity (or class/literal)."
            )

    # Check predicate (must be declared as type="predicate")
    if pred_normalized not in _declared_entities:
        errors.append(
            f"predicate '{pred_normalized}' not declared. Call: "
            f"kg_declare_entity(name='{predicate}', description='...', kind='predicate')"
        )
    else:
        pred_entity = _kg.get_entity(pred_normalized)
        if pred_entity and pred_entity.get("kind") != "predicate":
            errors.append(
                f"'{pred_normalized}' is kind='{pred_entity.get('kind')}', not 'predicate'. "
                f"Predicates must be declared with kind='predicate'."
            )

    # Check object (must be declared, must NOT be a predicate)
    if obj_normalized not in _declared_entities:
        errors.append(
            f"object '{obj_normalized}' not declared. Call: "
            f"kg_declare_entity(name='{object}', description='...', kind='entity')"
        )
    else:
        obj_entity = _kg.get_entity(obj_normalized)
        if obj_entity and obj_entity.get("kind") == "predicate":
            errors.append(
                f"object '{obj_normalized}' is kind=predicate, not an entity. "
                f"Objects must be kind=entity (or class/literal)."
            )

    if errors:
        return {
            "success": False,
            "error": "Declaration validation failed for kg_add.",
            "issues": errors,
        }

    # ── Class inheritance helper ──
    def _is_subclass_of(entity_classes, allowed_classes, max_depth=5):
        """Check if any of entity_classes is a subclass of any allowed_class.

        Walks is-a edges upward from each entity class. If it reaches an
        allowed class within max_depth hops, returns True. This enables
        class inheritance: if 'system is-a thing' and constraint allows
        'thing', then any system entity passes.
        """
        if not allowed_classes:
            return True  # no constraint = pass
        # Direct match first
        if any(c in allowed_classes for c in entity_classes):
            return True
        # Walk is-a hierarchy upward
        visited = set(entity_classes)
        frontier = list(entity_classes)
        for _ in range(max_depth):
            next_frontier = []
            for cls in frontier:
                parent_edges = _kg.query_entity(cls, direction="outgoing")
                for e in parent_edges:
                    if e["predicate"] == "is-a" and e["current"]:
                        parent = e["object"]
                        if parent in allowed_classes:
                            return True
                        if parent not in visited:
                            visited.add(parent)
                            next_frontier.append(parent)
            frontier = next_frontier
            if not frontier:
                break
        return False

    # ── Constraint enforcement ──
    constraint_errors = []
    if pred_entity:
        props = pred_entity.get("properties", {})
        if isinstance(props, str):
            import json as _json
            try:
                props = _json.loads(props)
            except Exception:
                props = {}
        pred_constraints = props.get("constraints", {})

        if pred_constraints:
            # Check subject kind constraint
            allowed_sub_kinds = pred_constraints.get("subject_kinds", [])
            if allowed_sub_kinds and sub_entity:
                sub_kind = sub_entity.get("kind", "entity")
                if sub_kind not in allowed_sub_kinds:
                    constraint_errors.append(
                        f"Subject kind mismatch: '{sub_normalized}' is kind='{sub_kind}', "
                        f"but predicate '{pred_normalized}' expects subject kind in {allowed_sub_kinds}."
                    )

            # Check subject class constraint (via is-a edges)
            allowed_sub_classes = pred_constraints.get("subject_classes", [])
            if allowed_sub_classes and sub_entity:
                sub_classes = [
                    e["object"] for e in _kg.query_entity(sub_normalized, direction="outgoing")
                    if e["predicate"] == "is-a" and e["current"]
                ]
                if sub_classes and not _is_subclass_of(sub_classes, allowed_sub_classes):
                    constraint_errors.append(
                        f"Subject class mismatch: '{sub_normalized}' is-a {sub_classes}, "
                        f"but predicate '{pred_normalized}' expects subject is-a {allowed_sub_classes}. "
                        f"Options: (1) wrong edge — use a different subject, "
                        f"(2) wrong predicate — check kg_list_declared() for a better fit, "
                        f"(3) missing classification — add is-a edge for '{sub_normalized}', "
                        f"(4) update predicate constraints, "
                        f"(5) create a more specific predicate, "
                        f"(6) rephrase with a more specific entity."
                    )

            # Check object kind constraint
            allowed_obj_kinds = pred_constraints.get("object_kinds", [])
            if allowed_obj_kinds and obj_entity:
                obj_kind = obj_entity.get("kind", "entity")
                if obj_kind not in allowed_obj_kinds:
                    constraint_errors.append(
                        f"Object kind mismatch: '{obj_normalized}' is kind='{obj_kind}', "
                        f"but predicate '{pred_normalized}' expects object kind in {allowed_obj_kinds}."
                    )

            # Check object class constraint
            allowed_obj_classes = pred_constraints.get("object_classes", [])
            if allowed_obj_classes and obj_entity:
                obj_classes = [
                    e["object"] for e in _kg.query_entity(obj_normalized, direction="outgoing")
                    if e["predicate"] == "is-a" and e["current"]
                ]
                if obj_classes and not _is_subclass_of(obj_classes, allowed_obj_classes):
                    constraint_errors.append(
                        f"Object class mismatch: '{obj_normalized}' is-a {obj_classes}, "
                        f"but predicate '{pred_normalized}' expects object is-a {allowed_obj_classes}. "
                        f"Options: (1) wrong edge, (2) wrong predicate, (3) missing classification, "
                        f"(4) update constraints, (5) new predicate, (6) rephrase with specific entity."
                    )

            # Check cardinality constraint
            cardinality = pred_constraints.get("cardinality", "many-to-many")
            if cardinality in ("many-to-one", "one-to-one"):
                # Subject can have at most 1 edge with this predicate
                existing_sub = [
                    e for e in _kg.query_entity(sub_normalized, direction="outgoing")
                    if e["predicate"] == pred_normalized and e["current"]
                ]
                if existing_sub:
                    existing_obj = existing_sub[0]["object"]
                    constraint_errors.append(
                        f"Cardinality violation: '{sub_normalized}' already has "
                        f"'{pred_normalized}' -> '{existing_obj}'. "
                        f"Predicate cardinality is {cardinality} (one target per subject). "
                        f"Options: (1) REPLACE — invalidate the old edge first, then add new, "
                        f"(2) MISTAKE — you meant a different predicate or entity, "
                        f"(3) EXPAND — change predicate cardinality to many-to-many."
                    )
            if cardinality in ("one-to-many", "one-to-one"):
                # Object can have at most 1 incoming edge with this predicate
                existing_obj = [
                    e for e in _kg.query_entity(obj_normalized, direction="incoming")
                    if e["predicate"] == pred_normalized and e["current"]
                ]
                if existing_obj:
                    existing_sub = existing_obj[0]["subject"]
                    constraint_errors.append(
                        f"Cardinality violation: '{obj_normalized}' already has incoming "
                        f"'{existing_sub}' -> '{pred_normalized}'. "
                        f"Predicate cardinality is {cardinality} (one source per object). "
                        f"Options: (1) REPLACE, (2) MISTAKE, (3) EXPAND cardinality."
                    )

    if constraint_errors:
        return {
            "success": False,
            "error": "Predicate constraint violation.",
            "constraint_issues": constraint_errors,
        }

    _wal_log(
        "kg_add",
        {
            "subject": subject,
            "predicate": predicate,
            "object": object,
            "valid_from": valid_from,
            "source_closet": source_closet,
        },
    )
    triple_id = _kg.add_triple(
        subject, predicate, object, valid_from=valid_from, source_closet=source_closet
    )
    return {"success": True, "triple_id": triple_id, "fact": f"{subject} -> {predicate} -> {object}"}


def tool_kg_invalidate(subject: str, predicate: str, object: str, ended: str = None):
    """Mark a fact as no longer true (set end date)."""
    _wal_log(
        "kg_invalidate",
        {"subject": subject, "predicate": predicate, "object": object, "ended": ended},
    )
    _kg.invalidate(subject, predicate, object, ended=ended)
    return {
        "success": True,
        "fact": f"{subject} → {predicate} → {object}",
        "ended": ended or "today",
    }


def tool_kg_timeline(entity: str = None):
    """Get chronological timeline of facts, optionally for one entity."""
    results = _kg.timeline(entity)
    return {"entity": entity or "all", "timeline": results, "count": len(results)}


def tool_kg_stats():
    """Knowledge graph overview: entities, triples, relationship types."""
    return _kg.stats()


# ==================== ENTITY DECLARATION ====================

ENTITY_SIMILARITY_THRESHOLD = 0.85
ENTITY_COLLECTION_NAME = "mempalace_entities"

# Session-level declared entities (in-memory for current process)
_declared_entities: set = set()
_session_id: str = ""


def _get_entity_collection(create: bool = True):
    """Get or create the mempalace_entities ChromaDB collection for description similarity."""
    try:
        client = chromadb.PersistentClient(path=_config.palace_path)
        if create:
            return client.get_or_create_collection(ENTITY_COLLECTION_NAME)
        else:
            return client.get_collection(ENTITY_COLLECTION_NAME)
    except Exception:
        if create:
            try:
                client = chromadb.PersistentClient(path=_config.palace_path)
                return client.create_collection(ENTITY_COLLECTION_NAME)
            except Exception:
                return None
        return None


def _reset_declared_entities():
    """Reset the session's declared entities set (called on compact/clear/restart)."""
    global _declared_entities, _session_id
    _declared_entities = set()
    _session_id = ""


def _check_entity_similarity(
    description: str,
    kind_filter: str = None,
    exclude_id: str = None,
    threshold: float = None,
):
    """Check if a description is semantically similar to existing entities.

    Args:
        description: the description to check against existing entities.
        kind_filter: if provided, only check against entities of this type.
                     This creates type-scoped collision domains: systems
                     only collide with systems, predicates only with predicates.
        exclude_id: entity ID to exclude from results (self-check).
        threshold: similarity threshold (default ENTITY_SIMILARITY_THRESHOLD).

    Returns list of similar entities above threshold.
    """
    threshold = threshold or ENTITY_SIMILARITY_THRESHOLD
    ecol = _get_entity_collection(create=False)
    if not ecol:
        return []
    try:
        count = ecol.count()
        if count == 0:
            return []
        query_kwargs = {
            "query_texts": [description],
            "n_results": min(10, count),
            "include": ["documents", "metadatas", "distances"],
        }
        # Kind-scoped collision: only check against same kind
        if kind_filter:
            query_kwargs["where"] = {}
        results = ecol.query(**query_kwargs)
        similar = []
        if results["ids"] and results["ids"][0]:
            for i, eid in enumerate(results["ids"][0]):
                if eid == exclude_id:
                    continue
                dist = results["distances"][0][i]
                similarity = round(1 - dist, 3)
                if similarity >= threshold:
                    meta = results["metadatas"][0][i]
                    doc = results["documents"][0][i]
                    similar.append({
                        "entity_id": eid,
                        "name": meta.get("name", eid),
                        "description": doc,
                        "similarity": similarity,
                        "importance": meta.get("importance", 3),
                    })
        return similar
    except Exception:
        return []


def _sync_entity_to_chromadb(entity_id: str, name: str, description: str, kind: str, importance: int):
    """Sync an entity's description to the ChromaDB collection for similarity search."""
    ecol = _get_entity_collection(create=True)
    if not ecol:
        return
    ecol.upsert(
        ids=[entity_id],
        documents=[description],
        metadatas=[{
            "name": name,
            
            "importance": importance,
            "last_touched": datetime.now().isoformat(),
        }],
    )


VALID_CARDINALITIES = {"many-to-many", "many-to-one", "one-to-many", "one-to-one"}


def tool_kg_declare_entity(
    name: str,
    description: str,
    kind: str = None,  # REQUIRED — no default, model must choose
    importance: int = 3,
    constraints: dict = None,  # REQUIRED when kind=predicate
):
    """Declare an entity before using it in KG edges. REQUIRED per session.

    Every entity used in kg_add (subject, predicate, or object) must be
    declared first. Declaration triggers similarity check against existing
    entities OF THE SAME KIND. If a collision is found (similarity > 0.85),
    the entity is BLOCKED until disambiguated or merged.

    Args:
        name: Entity name. Aggressively normalized (hyphens, underscores,
              CamelCase, articles all collapsed).
        description: Precise, unambiguous description.
              BAD:  "a server" (too generic, will collide with many entities)
              GOOD: "The DSpot paperclip platform server, started via pnpm
                     dev:once, listening on port 3100"
        kind: Ontological role — FIXED enum:
              'entity' (default) — a concrete individual thing
              'predicate' — a relationship type (use for KG edge labels)
              'class' — a category definition (domain type that entities is_a)
              'literal' — a raw value (string, number, timestamp)
              Collision detection is KIND-SCOPED: predicates only collide with
              predicates, entities only with entities, etc.
        importance: 1-5. 5=critical (production systems, hard rules),
                    4=canonical, 3=default, 2=low, 1=junk.

    Returns:
        status "created" — new entity, registered in session declared set.
        status "exists"  — entity already exists, registered in session.
        status "collision" — similar entities found, NOT registered.
                            You MUST resolve before using this entity.
    """
    from .knowledge_graph import normalize_entity_name

    try:
        description = sanitize_content(description, max_length=5000)
        importance = _validate_importance(importance)
        kind = _validate_kind(kind)
    except ValueError as e:
        return {"success": False, "error": str(e)}

    # Validate constraints for predicates
    if kind == "predicate":
        if not constraints:
            return {
                "success": False,
                "error": (
                    "Predicates REQUIRE constraints. Provide constraints dict with at least "
                    "'subject_kinds' and 'object_kinds'. Example: "
                    "constraints={'subject_kinds': ['entity'], 'object_kinds': ['entity'], "
                    "'cardinality': 'many-to-many'}"
                ),
            }
        # Validate constraint fields
        for field in ("subject_kinds", "object_kinds"):
            if field not in constraints:
                return {"success": False, "error": f"constraints must include '{field}'."}
            vals = constraints[field]
            if not isinstance(vals, list) or not vals:
                return {"success": False, "error": f"constraints['{field}'] must be a non-empty list of kinds."}
            for v in vals:
                if v not in VALID_KINDS:
                    return {"success": False, "error": f"constraints['{field}'] contains invalid kind '{v}'. Valid: {sorted(VALID_KINDS)}."}
        if "cardinality" in constraints:
            if constraints["cardinality"] not in VALID_CARDINALITIES:
                return {"success": False, "error": f"constraints['cardinality'] must be one of {sorted(VALID_CARDINALITIES)}."}
        else:
            constraints["cardinality"] = "many-to-many"
        # Validate subject_classes / object_classes reference real class-kind entities
        for cls_field in ("subject_classes", "object_classes"):
            if cls_field in constraints:
                cls_list = constraints[cls_field]
                if not isinstance(cls_list, list):
                    return {"success": False, "error": f"constraints['{cls_field}'] must be a list of class entity names."}
                for cls_name in cls_list:
                    from .knowledge_graph import normalize_entity_name as _norm
                    cls_entity = _kg.get_entity(_norm(cls_name))
                    if not cls_entity:
                        return {"success": False, "error": f"constraints['{cls_field}'] references class '{cls_name}' which doesn't exist. Declare it first with kind='class'."}
                    if cls_entity.get("kind") != "class":
                        return {"success": False, "error": f"constraints['{cls_field}'] references '{cls_name}' which is kind='{cls_entity.get('kind')}', not 'class'."}

    normalized = normalize_entity_name(name)
    if not normalized or normalized == "unknown":
        return {"success": False, "error": f"Entity name '{name}' normalizes to nothing. Use a more descriptive name."}

    # Check for exact match (already exists)
    existing = _kg.get_entity(normalized)
    if existing:
        # Check for collisions with OTHER entities of SAME KIND (not self)
        similar = _check_entity_similarity(description, kind_filter=kind, exclude_id=normalized)
        if similar:
            return {
                "success": False,
                "status": "collision",
                "entity_id": normalized,
                "kind": kind,
                "message": (
                    f"Entity '{normalized}' (kind={kind}) collides with other {kind}s. "
                    f"Disambiguate via kg_update_entity_description or merge via kg_merge_entities."
                ),
                "collisions": similar,
            }
        # No collisions — register in session
        _declared_entities.add(normalized)
        # Update description + importance + kind if provided and different
        if description and description != existing.get("description", ""):
            _kg.update_entity_description(normalized, description, importance)
            _sync_entity_to_chromadb(normalized, name, description, kind, importance or 3)
        return {
            "success": True,
            "status": "exists",
            "entity_id": normalized,
            "kind": existing.get("kind", "entity"),
            "description": existing.get("description") or description,
            "importance": existing.get("importance", 3),
            "edge_count": _kg.entity_edge_count(normalized),
        }

    # New entity — check for collisions via description similarity (same KIND only)
    similar = _check_entity_similarity(description, kind_filter=kind)
    if similar:
        return {
            "success": False,
            "status": "collision",
            "entity_id": normalized,
            "message": (
                f"Cannot create entity '{normalized}': its description is too similar to existing entities. "
                f"Either (1) merge with the matching entity via kg_merge_entities(source='{normalized}', "
                f"target='{similar[0]['entity_id']}'), or (2) rewrite your description to be more "
                f"specific and re-declare. The entity is NOT usable until resolved."
            ),
            "collisions": similar,
        }

    # No collisions — create the entity
    props = {"constraints": constraints} if constraints else {}
    _kg.add_entity(name, description=description, importance=importance or 3, kind=kind, properties=props)
    _sync_entity_to_chromadb(normalized, name, description, kind, importance or 3)
    _declared_entities.add(normalized)

    _wal_log("kg_declare_entity", {
        "entity_id": normalized,
        "name": name,
        "description": description[:200],
        "kind": kind,
        
        "importance": importance,
    })

    return {
        "success": True,
        "status": "created",
        "entity_id": normalized,
        "kind": kind,
        "description": description,
        "importance": importance or 3,
        
    }


def tool_kg_update_entity_description(
    entity: str,
    new_description: str,
    check_against: str = None,
):
    """Update an entity's description and check distance from colliding entities.

    Use after kg_declare_entity returns 'collision'. Update the description
    to make it semantically distinct from the colliding entity, then re-declare.

    Args:
        entity: The entity to update.
        new_description: The improved, more specific description.
        check_against: Entity to measure distance from (optional).
                       If not provided, checks against all entities above threshold.

    Returns:
        Distance checks with similarity scores and is_distinct flags.
    """
    from .knowledge_graph import normalize_entity_name

    try:
        new_description = sanitize_content(new_description, max_length=5000)
    except ValueError as e:
        return {"success": False, "error": str(e)}

    normalized = normalize_entity_name(entity)
    existing = _kg.get_entity(normalized)
    if not existing:
        return {"success": False, "error": f"Entity '{normalized}' not found."}

    # Update in SQLite + ChromaDB
    updated = _kg.update_entity_description(normalized, new_description)
    _sync_entity_to_chromadb(
        normalized, existing["name"], new_description,
        existing.get("type", "concept"), existing.get("importance", 3)
    )

    # Distance checks
    distance_checks = []
    if check_against:
        check_id = normalize_entity_name(check_against)
        check_entity = _kg.get_entity(check_id)
        if check_entity:
            similar = _check_entity_similarity(new_description, exclude_id=normalized, threshold=0.0)
            for s in similar:
                if s["entity_id"] == check_id:
                    distance_checks.append({
                        "compared_to": check_id,
                        "similarity": s["similarity"],
                        "is_distinct": s["similarity"] < ENTITY_SIMILARITY_THRESHOLD,
                        "threshold": ENTITY_SIMILARITY_THRESHOLD,
                    })
                    break
            else:
                distance_checks.append({
                    "compared_to": check_id,
                    "similarity": 0.0,
                    "is_distinct": True,
                    "threshold": ENTITY_SIMILARITY_THRESHOLD,
                })
    else:
        # Check against all entities above a low threshold
        similar = _check_entity_similarity(new_description, exclude_id=normalized, threshold=0.7)
        for s in similar:
            distance_checks.append({
                "compared_to": s["entity_id"],
                "similarity": s["similarity"],
                "is_distinct": s["similarity"] < ENTITY_SIMILARITY_THRESHOLD,
                "threshold": ENTITY_SIMILARITY_THRESHOLD,
            })

    all_distinct = all(d["is_distinct"] for d in distance_checks) if distance_checks else True

    return {
        "success": True,
        "entity_id": normalized,
        "description_updated": True,
        "new_description": new_description,
        "distance_checks": distance_checks,
        "all_distinct": all_distinct,
        "hint": "All clear — re-declare this entity to register it." if all_distinct
                else "Still too similar to some entities. Make your description more specific.",
    }


def tool_kg_merge_entities(source: str, target: str, update_description: str = None):
    """Merge source entity into target. All edges rewritten. Source becomes alias.

    Use when kg_declare_entity returns 'collision' and the entities are
    actually the same thing. All triples from source are moved to target.
    Source name becomes an alias that auto-resolves to target in future queries.

    Args:
        source: Entity to merge FROM (will be soft-deleted).
        target: Entity to merge INTO (will be kept, edges grow).
        update_description: Optional new description for the merged entity.
    """
    _wal_log("kg_merge_entities", {
        "source": source,
        "target": target,
        "update_description": update_description[:200] if update_description else None,
    })

    result = _kg.merge_entities(source, target, update_description)
    if "error" in result:
        return {"success": False, "error": result["error"]}

    # Update ChromaDB: remove source, update target
    from .knowledge_graph import normalize_entity_name
    source_id = normalize_entity_name(source)
    target_id = normalize_entity_name(target)

    ecol = _get_entity_collection(create=False)
    if ecol:
        try:
            ecol.delete(ids=[source_id])
        except Exception:
            pass
        target_entity = _kg.get_entity(target_id)
        if target_entity:
            _sync_entity_to_chromadb(
                target_id, target_entity["name"],
                target_entity["description"], target_entity.get("type", "concept"),
                target_entity.get("importance", 3)
            )

    # Register target as declared (source is now alias for target)
    _declared_entities.discard(source_id)
    _declared_entities.add(target_id)

    return {
        "success": True,
        "source": result["source"],
        "target": result["target"],
        "edges_moved": result["edges_moved"],
        "aliases_created": result["aliases_created"],
    }


def tool_kg_update_predicate_constraints(
    predicate: str,
    constraints: dict,
):
    """Update constraints on an existing predicate entity.

    Use when: a predicate's constraints are too narrow or too broad,
    or when seeding constraints on predicates that lack them.

    Args:
        predicate: the predicate entity name
        constraints: new constraints dict with subject_kinds, object_kinds,
                     optional subject_classes, object_classes, cardinality.
    """
    from .knowledge_graph import normalize_entity_name
    import json as _json

    normalized = normalize_entity_name(predicate)
    entity = _kg.get_entity(normalized)
    if not entity:
        return {"success": False, "error": f"Predicate '{normalized}' not found."}
    if entity.get("kind") != "predicate":
        return {"success": False, "error": f"'{normalized}' is kind='{entity.get('kind')}', not 'predicate'."}

    # Validate constraints
    for field in ("subject_kinds", "object_kinds"):
        if field not in constraints:
            return {"success": False, "error": f"constraints must include '{field}'."}
        vals = constraints[field]
        if not isinstance(vals, list) or not vals:
            return {"success": False, "error": f"constraints['{field}'] must be a non-empty list."}
        for v in vals:
            if v not in VALID_KINDS:
                return {"success": False, "error": f"Invalid kind '{v}' in constraints['{field}']. Valid: {sorted(VALID_KINDS)}."}
    if "cardinality" in constraints:
        if constraints["cardinality"] not in VALID_CARDINALITIES:
            return {"success": False, "error": f"Invalid cardinality. Valid: {sorted(VALID_CARDINALITIES)}."}
    # Validate class references
    for cls_field in ("subject_classes", "object_classes"):
        if cls_field in constraints:
            for cls_name in constraints[cls_field]:
                cls_eid = normalize_entity_name(cls_name)
                cls_ent = _kg.get_entity(cls_eid)
                if not cls_ent:
                    return {"success": False, "error": f"Class '{cls_name}' not found. Declare with kind='class' first."}
                if cls_ent.get("kind") != "class":
                    return {"success": False, "error": f"'{cls_name}' is kind='{cls_ent.get('kind')}', not 'class'."}

    # Update properties
    conn = _kg._conn()
    existing_props = entity.get("properties", {})
    if isinstance(existing_props, str):
        try:
            existing_props = _json.loads(existing_props)
        except Exception:
            existing_props = {}
    existing_props["constraints"] = constraints
    conn.execute(
        "UPDATE entities SET properties = ? WHERE id = ?",
        (_json.dumps(existing_props), normalized),
    )
    conn.commit()

    return {
        "success": True,
        "predicate": normalized,
        "constraints": constraints,
    }


def tool_kg_list_declared():
    """List all entities declared in this session."""
    results = []
    for eid in sorted(_declared_entities):
        entity = _kg.get_entity(eid)
        if entity:
            results.append({
                "entity_id": eid,
                "name": entity["name"],
                "description": entity["description"],
                "importance": entity["importance"],
                "last_touched": entity["last_touched"],
                "edge_count": _kg.entity_edge_count(eid),
            })
    return {
        "declared_count": len(results),
        "entities": results,
    }


def tool_kg_entity_info(entity: str):
    """Get full details for an entity: description, edges, linked drawers.

    Entity must be declared in this session to query.
    """
    from .knowledge_graph import normalize_entity_name
    normalized = normalize_entity_name(entity)

    if normalized not in _declared_entities:
        return {
            "success": False,
            "error": (
                f"Entity '{normalized}' has not been declared in this session. "
                f"Call kg_declare_entity(name='{entity}', description='...') first. "
                f"All entities must be declared before use."
            ),
        }

    info = _kg.get_entity(normalized)
    if not info:
        return {"success": False, "error": f"Entity '{normalized}' not found in KG."}

    edges = _kg.query_entity(normalized, direction="both")
    return {
        "success": True,
        "entity_id": normalized,
        "name": info["name"],
        "description": info["description"],
        "type": info["type"],
        "importance": info["importance"],
        "last_touched": info["last_touched"],
        "status": info["status"],
        "edge_count": len(edges),
        "edges": edges,
    }


# ==================== AGENT DIARY ====================


def tool_diary_write(
    agent_name: str,
    entry: str,
    topic: str = "general",
    hall: str = "hall_diary",
    importance: int = None,
):
    """
    Write a diary entry for this agent. Each agent gets its own wing
    with a diary room. Entries are timestamped and accumulate over time.

    This is the agent's personal journal — observations, thoughts,
    what it worked on, what it noticed, what it thinks matters.

    Optional:
        hall: default 'hall_diary'. Override with 'hall_discoveries' for
              "today I learned" entries that deserve higher retrieval priority,
              or 'hall_events' for plain activity logs.
        importance: 1-5. Defaults to unset (treated as 3 by L1). Use 4 for
                    entries with learned lessons, 5 only for agent-wide
                    critical notes.
    """
    try:
        agent_name = sanitize_name(agent_name, "agent_name")
        entry = sanitize_content(entry)
        hall = _validate_hall(hall)
        importance = _validate_importance(importance)
    except ValueError as e:
        return {"success": False, "error": str(e)}

    wing = f"wing_{agent_name.lower().replace(' ', '_')}"
    room = "diary"
    col = _get_collection(create=True)
    if not col:
        return _no_palace()

    now = datetime.now()
    entry_id = f"diary_{wing}_{now.strftime('%Y%m%d_%H%M%S')}_{hashlib.sha256(entry[:50].encode()).hexdigest()[:12]}"

    _wal_log(
        "diary_write",
        {
            "agent_name": agent_name,
            "topic": topic,
            "entry_id": entry_id,
            "entry_preview": entry[:200],
            "hall": hall,
            "importance": importance,
        },
    )

    try:
        # TODO: Future versions should expand AAAK before embedding to improve
        # semantic search quality. For now, store raw AAAK in metadata so it's
        # preserved, and keep the document as-is for embedding (even though
        # compressed AAAK degrades embedding quality).
        meta = {
            "wing": wing,
            "room": room,
            "hall": hall or "hall_diary",
            "topic": topic,
            "type": "diary_entry",
            "agent": agent_name,
            "filed_at": now.isoformat(),
            "date_added": now.isoformat(),
            "date": now.strftime("%Y-%m-%d"),
        }
        if importance is not None:
            meta["importance"] = importance
        col.add(
            ids=[entry_id],
            documents=[entry],
            metadatas=[meta],
        )
        logger.info(f"Diary entry: {entry_id} -> {wing}/diary/{topic} hall={hall} imp={importance}")
        return {
            "success": True,
            "entry_id": entry_id,
            "agent": agent_name,
            "topic": topic,
            "hall": hall,
            "importance": importance,
            "timestamp": now.isoformat(),
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def tool_diary_read(agent_name: str, last_n: int = 10):
    """
    Read an agent's recent diary entries. Returns the last N entries
    in chronological order — the agent's personal journal.
    """
    wing = f"wing_{agent_name.lower().replace(' ', '_')}"
    col = _get_collection()
    if not col:
        return _no_palace()

    try:
        results = col.get(
            where={"$and": [{"wing": wing}, {"room": "diary"}]},
            include=["documents", "metadatas"],
            limit=10000,
        )

        if not results["ids"]:
            return {"agent": agent_name, "entries": [], "message": "No diary entries yet."}

        # Combine and sort by timestamp
        entries = []
        for doc, meta in zip(results["documents"], results["metadatas"]):
            entries.append(
                {
                    "date": meta.get("date", ""),
                    "timestamp": meta.get("filed_at", ""),
                    "topic": meta.get("topic", ""),
                    "content": doc,
                }
            )

        entries.sort(key=lambda x: x["timestamp"], reverse=True)
        entries = entries[:last_n]

        return {
            "agent": agent_name,
            "entries": entries,
            "total": len(results["ids"]),
            "showing": len(entries),
        }
    except Exception as e:
        return {"error": str(e)}


# ==================== MCP PROTOCOL ====================

TOOLS = {
    "mempalace_status": {
        "description": "Palace overview — total drawers, wing and room counts",
        "input_schema": {"type": "object", "properties": {}},
        "handler": tool_status,
    },
    "mempalace_list_wings": {
        "description": "List all wings with drawer counts",
        "input_schema": {"type": "object", "properties": {}},
        "handler": tool_list_wings,
    },
    "mempalace_list_rooms": {
        "description": "List rooms within a wing (or all rooms if no wing given)",
        "input_schema": {
            "type": "object",
            "properties": {
                "wing": {"type": "string", "description": "Wing to list rooms for (optional)"},
            },
        },
        "handler": tool_list_rooms,
    },
    "mempalace_get_taxonomy": {
        "description": "Full taxonomy: wing → room → drawer count",
        "input_schema": {"type": "object", "properties": {}},
        "handler": tool_get_taxonomy,
    },
    "mempalace_get_aaak_spec": {
        "description": "Get the AAAK dialect specification — the compressed memory format MemPalace uses. Call this if you need to read or write AAAK-compressed memories.",
        "input_schema": {"type": "object", "properties": {}},
        "handler": tool_get_aaak_spec,
    },
    "mempalace_kg_query": {
        "description": "Query the knowledge graph for an entity's relationships. Returns typed facts with temporal validity. E.g. 'Max' → child_of Alice, loves chess, does swimming. Filter by date with as_of to see what was true at a point in time.",
        "input_schema": {
            "type": "object",
            "properties": {
                "entity": {
                    "type": "string",
                    "description": "Entity to query (e.g. 'Max', 'MyProject', 'Alice')",
                },
                "as_of": {
                    "type": "string",
                    "description": "Date filter — only facts valid at this date (YYYY-MM-DD, optional)",
                },
                "direction": {
                    "type": "string",
                    "description": "outgoing (entity→?), incoming (?→entity), or both (default: both)",
                },
            },
            "required": ["entity"],
        },
        "handler": tool_kg_query,
    },
    "mempalace_kg_add": {
        "description": "Add a fact to the knowledge graph. Subject → predicate → object with optional time window. E.g. ('Max', 'started_school', 'Year 7', valid_from='2026-09-01').",
        "input_schema": {
            "type": "object",
            "properties": {
                "subject": {"type": "string", "description": "The entity doing/being something"},
                "predicate": {
                    "type": "string",
                    "description": "The relationship type (e.g. 'loves', 'works_on', 'daughter_of')",
                },
                "object": {"type": "string", "description": "The entity being connected to"},
                "valid_from": {
                    "type": "string",
                    "description": "When this became true (YYYY-MM-DD, optional)",
                },
                "source_closet": {
                    "type": "string",
                    "description": "Closet ID where this fact appears (optional)",
                },
            },
            "required": ["subject", "predicate", "object"],
        },
        "handler": tool_kg_add,
    },
    "mempalace_kg_invalidate": {
        "description": "Mark a fact as no longer true. E.g. ankle injury resolved, job ended, moved house.",
        "input_schema": {
            "type": "object",
            "properties": {
                "subject": {"type": "string", "description": "Entity"},
                "predicate": {"type": "string", "description": "Relationship"},
                "object": {"type": "string", "description": "Connected entity"},
                "ended": {
                    "type": "string",
                    "description": "When it stopped being true (YYYY-MM-DD, default: today)",
                },
            },
            "required": ["subject", "predicate", "object"],
        },
        "handler": tool_kg_invalidate,
    },
    "mempalace_kg_timeline": {
        "description": "Chronological timeline of facts. Shows the story of an entity (or everything) in order.",
        "input_schema": {
            "type": "object",
            "properties": {
                "entity": {
                    "type": "string",
                    "description": "Entity to get timeline for (optional — omit for full timeline)",
                },
            },
        },
        "handler": tool_kg_timeline,
    },
    "mempalace_kg_stats": {
        "description": "Knowledge graph overview: entities, triples, current vs expired facts, relationship types.",
        "input_schema": {"type": "object", "properties": {}},
        "handler": tool_kg_stats,
    },
    "mempalace_kg_declare_entity": {
        "description": "REQUIRED before using any entity in kg_add. Declare an entity with a precise description. Triggers KIND-SCOPED similarity check (entities only collide with entities, predicates only with predicates). Collision BLOCKS the entity until disambiguated or merged. Use kind='predicate' for relationship types, kind='class' for category definitions, kind='entity' (default) for concrete things.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Entity name (will be normalized: hyphens/underscores/CamelCase all collapsed)"},
                "description": {
                    "type": "string",
                    "description": "Precise description. BAD: 'a server'. GOOD: 'The DSpot paperclip platform server, started via pnpm dev:once, listening on port 3100'. Generic descriptions collide with many entities, forcing disambiguation.",
                },
                "kind": {
                    "type": "string",
                    "description": "Ontological role (FIXED 4 values): 'entity' (default, concrete thing), 'predicate' (relationship type for kg_add edges), 'class' (category definition, other entities is_a this), 'literal' (raw value).",
                    "enum": ["entity", "predicate", "class", "literal"],
                },
                "importance": {
                    "type": "integer",
                    "description": "1-5. 5=critical, 4=canonical, 3=default, 2=low, 1=junk.",
                    "minimum": 1,
                    "maximum": 5,
                },
                "constraints": {
                    "type": "object",
                    "description": "REQUIRED when kind=predicate. Defines what subject/object types this predicate accepts. Fields: subject_kinds (list of valid kinds), object_kinds (list), subject_classes (optional list of domain types via is-a), object_classes (optional), cardinality ('many-to-many'|'many-to-one'|'one-to-many'|'one-to-one', default many-to-many). Example: {'subject_kinds':['entity'],'object_kinds':['entity'],'subject_classes':['system','process'],'cardinality':'many-to-one'}",
                },
            },
            "required": ["name", "description", "kind", "importance"],
        },
        "handler": tool_kg_declare_entity,
    },
    "mempalace_kg_update_entity_description": {
        "description": "Update an entity's description to disambiguate from colliding entities. Use after kg_declare_entity returns 'collision'. Returns distance checks showing whether the entities are now distinct enough.",
        "input_schema": {
            "type": "object",
            "properties": {
                "entity": {"type": "string", "description": "Entity to update"},
                "new_description": {"type": "string", "description": "Improved, more specific description"},
                "check_against": {"type": "string", "description": "Entity to measure distance from (optional — auto-checks all if omitted)"},
            },
            "required": ["entity", "new_description"],
        },
        "handler": tool_kg_update_entity_description,
    },
    "mempalace_kg_merge_entities": {
        "description": "Merge source entity into target. All edges rewritten, source becomes alias. Use when kg_declare_entity returns 'collision' and the entities are actually the same thing.",
        "input_schema": {
            "type": "object",
            "properties": {
                "source": {"type": "string", "description": "Entity to merge FROM (will be soft-deleted)"},
                "target": {"type": "string", "description": "Entity to merge INTO (will be kept)"},
                "update_description": {"type": "string", "description": "Optional new description for the merged entity"},
            },
            "required": ["source", "target"],
        },
        "handler": tool_kg_merge_entities,
    },
    "mempalace_kg_update_predicate_constraints": {
        "description": "Update constraints on an existing predicate. Use when constraints are too narrow/broad or when seeding constraints on predicates that lack them.",
        "input_schema": {
            "type": "object",
            "properties": {
                "predicate": {"type": "string", "description": "Predicate entity name to update"},
                "constraints": {
                    "type": "object",
                    "description": "New constraints: subject_kinds (required list), object_kinds (required list), subject_classes (optional list of class entities), object_classes (optional), cardinality (many-to-many|many-to-one|one-to-many|one-to-one).",
                },
            },
            "required": ["predicate", "constraints"],
        },
        "handler": tool_kg_update_predicate_constraints,
    },
    "mempalace_kg_list_declared": {
        "description": "List all entities declared in this session with their details (description, importance, edge count).",
        "input_schema": {"type": "object", "properties": {}},
        "handler": tool_kg_list_declared,
    },
    "mempalace_kg_entity_info": {
        "description": "Full details for a declared entity: description, importance, all edges (in+out), type. Entity must be declared this session.",
        "input_schema": {
            "type": "object",
            "properties": {
                "entity": {"type": "string", "description": "Entity name to inspect"},
            },
            "required": ["entity"],
        },
        "handler": tool_kg_entity_info,
    },
    "mempalace_traverse": {
        "description": "Walk the palace graph from a room. Shows connected ideas across wings — the tunnels. Like following a thread through the palace: start at 'chromadb-setup' in wing_code, discover it connects to wing_myproject (planning) and wing_user (feelings about it).",
        "input_schema": {
            "type": "object",
            "properties": {
                "start_room": {
                    "type": "string",
                    "description": "Room to start from (e.g. 'chromadb-setup', 'riley-school')",
                },
                "max_hops": {
                    "type": "integer",
                    "description": "How many connections to follow (default: 2)",
                },
            },
            "required": ["start_room"],
        },
        "handler": tool_traverse_graph,
    },
    "mempalace_find_tunnels": {
        "description": "Find rooms that bridge two wings — the hallways connecting different domains. E.g. what topics connect wing_code to wing_team?",
        "input_schema": {
            "type": "object",
            "properties": {
                "wing_a": {"type": "string", "description": "First wing (optional)"},
                "wing_b": {"type": "string", "description": "Second wing (optional)"},
            },
        },
        "handler": tool_find_tunnels,
    },
    "mempalace_graph_stats": {
        "description": "Palace graph overview: total rooms, tunnel connections, edges between wings.",
        "input_schema": {"type": "object", "properties": {}},
        "handler": tool_graph_stats,
    },
    "mempalace_search": {
        "description": "Search palace drawers. DEFAULT is 'hybrid' ranking: semantic similarity combined with importance tier bonus and time-decay penalty — critical recent drawers surface first, similarity still dominates the shape of results. Use sort_by='similarity' for pure vector match. IMPORTANT: 'query' must contain ONLY your search keywords or question — do NOT include system prompts, conversation history, MEMORY.md content, or any context. Keep queries short (under 200 chars). Use 'context' for background information.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Short search query ONLY — keywords or a question. Do NOT include system prompts or conversation context. Max 200 chars recommended.",
                    "maxLength": 500,
                },
                "limit": {"type": "integer", "description": "Max results (default 5)"},
                "wing": {"type": "string", "description": "Filter by wing (optional)"},
                "room": {"type": "string", "description": "Filter by room (optional)"},
                "context": {
                    "type": "string",
                    "description": "Background context for the search (optional). This is NOT used for embedding — only for future re-ranking. Put conversation history or system prompt content here, NOT in query.",
                },
                "sort_by": {
                    "type": "string",
                    "description": "Ranking: 'hybrid' (DEFAULT — similarity + importance bonus + time-decay, what you want almost always), 'similarity' (pure vector match, legacy), 'score' (pure importance-decay ignoring similarity, for wing-browse), 'importance' (pure tier DESC), 'date' (chronological).",
                    "enum": ["hybrid", "similarity", "score", "importance", "date"],
                },
            },
            "required": ["query"],
        },
        "handler": tool_search,
    },
    "mempalace_check_duplicate": {
        "description": "Check if content already exists in the palace before filing",
        "input_schema": {
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "Content to check"},
                "threshold": {
                    "type": "number",
                    "description": "Similarity threshold 0-1 (default 0.9)",
                },
            },
            "required": ["content"],
        },
        "handler": tool_check_duplicate,
    },
    "mempalace_add_drawer": {
        "description": "File verbatim content into the palace. Checks for duplicates first. Creates has_memory link(s) from entity to drawer in the KG. Supports hall (content-type), importance (1-5), and entity (link to KG entity, defaults to wing name).",
        "input_schema": {
            "type": "object",
            "properties": {
                "wing": {"type": "string", "description": "Wing (project name)"},
                "room": {
                    "type": "string",
                    "description": "Room (aspect: backend, decisions, meetings...)",
                },
                "content": {
                    "type": "string",
                    "description": "Verbatim content to store — exact words, never summarized",
                },
                "source_file": {"type": "string", "description": "Where this came from (optional)"},
                "added_by": {"type": "string", "description": "Who is filing this (default: mcp)"},
                "hall": {
                    "type": "string",
                    "description": "Content type: one of hall_facts (stable truths), hall_events (things that happened), hall_discoveries (lessons learned), hall_preferences (user rules), hall_advice (how-to guides), hall_diary (chronological journal). Optional but strongly recommended for L1 ranking.",
                    "enum": ["hall_facts", "hall_events", "hall_discoveries", "hall_preferences", "hall_advice", "hall_diary"],
                },
                "importance": {
                    "type": "integer",
                    "description": "Importance 1-5. 5=critical unmissable (secrets, hard rules, identity), 4=canonical rules/cookbooks, 3=default (historical events, diary), 2=low priority, 1=junk/quarantine. Used by Layer1 decay-aware ranking.",
                    "minimum": 1,
                    "maximum": 5,
                },
                "entity": {
                    "type": "string",
                    "description": "Entity name (or comma-separated list) to link this drawer to via has_memory edges in the KG. Defaults to the wing name if not provided. Every drawer should be discoverable via the entity graph — no orphan blobs.",
                },
            },
            "required": ["wing", "room", "content", "hall", "importance", "entity"],
        },
        "handler": tool_add_drawer,
    },
    "mempalace_delete_drawer": {
        "description": "Delete a drawer by ID. Irreversible.",
        "input_schema": {
            "type": "object",
            "properties": {
                "drawer_id": {"type": "string", "description": "ID of the drawer to delete"},
            },
            "required": ["drawer_id"],
        },
        "handler": tool_delete_drawer,
    },
    "mempalace_wake_up": {
        "description": "Return L0 (identity) + L1 (importance-ranked essential story) wake-up text (~600-900 tokens total). Call this ONCE at session start to load project/agent boot context. Replaces hand-rolled mempalace_search chains. L1 is ranked with importance-weighted time decay — critical facts always surface first, within-tier newer wins. Pass wing='ga' for GA sessions, wing='wing_<agent>' for paperclip agents.",
        "input_schema": {
            "type": "object",
            "properties": {
                "wing": {
                    "type": "string",
                    "description": "Optional wing filter. If unset, L1 loads globally. If set, L1 loads only drawers in that wing (project/agent-scoped boot).",
                },
            },
            "required": [],
        },
        "handler": tool_wake_up,
    },
    "mempalace_update_drawer_metadata": {
        "description": "Update metadata fields (wing, room, hall, importance) on an existing drawer in place. Preserves embeddings — no re-vectorization. Use for retroactive hall classification, importance bumping, or wing/room migrations. Any param left unset preserves the existing value.",
        "input_schema": {
            "type": "object",
            "properties": {
                "drawer_id": {"type": "string", "description": "ID of the drawer to update"},
                "wing": {"type": "string", "description": "New wing (optional — only if moving)"},
                "room": {"type": "string", "description": "New room (optional — only if moving)"},
                "hall": {
                    "type": "string",
                    "description": "New hall classification (optional). One of hall_facts, hall_events, hall_discoveries, hall_preferences, hall_advice, hall_diary.",
                    "enum": ["hall_facts", "hall_events", "hall_discoveries", "hall_preferences", "hall_advice", "hall_diary"],
                },
                "importance": {
                    "type": "integer",
                    "description": "New importance 1-5 (optional).",
                    "minimum": 1,
                    "maximum": 5,
                },
            },
            "required": ["drawer_id"],
        },
        "handler": tool_update_drawer_metadata,
    },
    "mempalace_diary_write": {
        "description": "Write to your personal agent diary in AAAK format. Your observations, thoughts, what you worked on, what matters. Each agent has their own diary with full history. Write in AAAK for compression — e.g. 'SESSION:2026-04-04|built.palace.graph+diary.tools|ALC.req:agent.diaries.in.aaak|★★★'. Use entity codes from the AAAK spec. Optional hall/importance for special entries.",
        "input_schema": {
            "type": "object",
            "properties": {
                "agent_name": {
                    "type": "string",
                    "description": "Your name — each agent gets their own diary wing",
                },
                "entry": {
                    "type": "string",
                    "description": "Your diary entry in AAAK format — compressed, entity-coded, emotion-marked",
                },
                "topic": {
                    "type": "string",
                    "description": "Topic tag (optional, default: general)",
                },
                "hall": {
                    "type": "string",
                    "description": "Override the default hall_diary classification. Use hall_discoveries for 'today I learned' entries worth higher retrieval priority, hall_events for plain activity logs.",
                    "enum": ["hall_facts", "hall_events", "hall_discoveries", "hall_preferences", "hall_advice", "hall_diary"],
                },
                "importance": {
                    "type": "integer",
                    "description": "Importance 1-5. Leave unset for default diary entries (treated as 3 by Layer1). Use 4 for entries with learned lessons, 5 only for agent-wide critical notes.",
                    "minimum": 1,
                    "maximum": 5,
                },
            },
            "required": ["agent_name", "entry"],
        },
        "handler": tool_diary_write,
    },
    "mempalace_diary_read": {
        "description": "Read your recent diary entries (in AAAK). See what past versions of yourself recorded — your journal across sessions.",
        "input_schema": {
            "type": "object",
            "properties": {
                "agent_name": {
                    "type": "string",
                    "description": "Your name — each agent gets their own diary wing",
                },
                "last_n": {
                    "type": "integer",
                    "description": "Number of recent entries to read (default: 10)",
                },
            },
            "required": ["agent_name"],
        },
        "handler": tool_diary_read,
    },
}


SUPPORTED_PROTOCOL_VERSIONS = [
    "2025-11-25",
    "2025-06-18",
    "2025-03-26",
    "2024-11-05",
]


def handle_request(request):
    method = request.get("method", "")
    params = request.get("params", {})
    req_id = request.get("id")

    if method == "initialize":
        client_version = params.get("protocolVersion", SUPPORTED_PROTOCOL_VERSIONS[-1])
        negotiated = (
            client_version
            if client_version in SUPPORTED_PROTOCOL_VERSIONS
            else SUPPORTED_PROTOCOL_VERSIONS[0]
        )
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": negotiated,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "mempalace", "version": __version__},
            },
        }
    elif method == "notifications/initialized":
        return None
    elif method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "tools": [
                    {"name": n, "description": t["description"], "inputSchema": t["input_schema"]}
                    for n, t in TOOLS.items()
                ]
            },
        }
    elif method == "tools/call":
        tool_name = params.get("name")
        tool_args = params.get("arguments") or {}
        if tool_name not in TOOLS:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32601, "message": f"Unknown tool: {tool_name}"},
            }
        # Coerce argument types based on input_schema.
        # MCP JSON transport may deliver integers as floats or strings;
        # ChromaDB and Python slicing require native int.
        schema_props = TOOLS[tool_name]["input_schema"].get("properties", {})
        for key, value in list(tool_args.items()):
            prop_schema = schema_props.get(key, {})
            declared_type = prop_schema.get("type")
            if declared_type == "integer" and not isinstance(value, int):
                tool_args[key] = int(value)
            elif declared_type == "number" and not isinstance(value, (int, float)):
                tool_args[key] = float(value)
        try:
            result = TOOLS[tool_name]["handler"](**tool_args)
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"content": [{"type": "text", "text": json.dumps(result, indent=2)}]},
            }
        except Exception:
            logger.exception(f"Tool error in {tool_name}")
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32000, "message": "Internal tool error"},
            }

    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {"code": -32601, "message": f"Unknown method: {method}"},
    }


def main():
    logger.info("MemPalace MCP Server starting...")
    while True:
        try:
            line = sys.stdin.readline()
            if not line:
                break
            line = line.strip()
            if not line:
                continue
            request = json.loads(line)
            response = handle_request(request)
            if response is not None:
                sys.stdout.write(json.dumps(response) + "\n")
                sys.stdout.flush()
        except KeyboardInterrupt:
            break
        except Exception as e:
            logger.error(f"Server error: {e}")


if __name__ == "__main__":
    main()
