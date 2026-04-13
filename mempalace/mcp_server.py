#!/usr/bin/env python3
"""
MemPalace MCP Server
====================
Supports both:
  - stdio transport for local MCP clients such as Claude Code
  - Streamable HTTP transport for remote MCP clients such as ChatGPT custom apps

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
import json
import hashlib
import logging
import os
import sys
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

import chromadb

from .config import MempalaceConfig, sanitize_content, sanitize_name
from .knowledge_graph import KnowledgeGraph
from .palace_graph import find_tunnels, graph_stats, traverse
from .query_sanitizer import sanitize_query
from .searcher import search_memories
from .version import __version__

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


def tool_search(
    query: str, limit: int = 5, wing: str = None, room: str = None, context: str = None
):
    # Mitigate system prompt contamination (Issue #333)
    sanitized = sanitize_query(query)
    result = search_memories(
        sanitized["clean_query"],
        palace_path=_config.palace_path,
        wing=wing,
        room=room,
        n_results=limit,
    )
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


def tool_add_drawer(
    wing: str, room: str, content: str, source_file: str = None, added_by: str = "mcp"
):
    """File verbatim content into a wing/room. Checks for duplicates first."""
    try:
        wing = sanitize_name(wing, "wing")
        room = sanitize_name(room, "room")
        content = sanitize_content(content)
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
        },
    )

    # Idempotency: if the deterministic ID already exists, return success as a no-op.
    try:
        existing = col.get(ids=[drawer_id])
        if existing and existing["ids"]:
            return {"success": True, "reason": "already_exists", "drawer_id": drawer_id}
    except Exception:
        pass

    try:
        col.upsert(
            ids=[drawer_id],
            documents=[content],
            metadatas=[
                {
                    "wing": wing,
                    "room": room,
                    "source_file": source_file or "",
                    "chunk_index": 0,
                    "added_by": added_by,
                    "filed_at": datetime.now().isoformat(),
                }
            ],
        )
        logger.info(f"Filed drawer: {drawer_id} → {wing}/{room}")
        return {"success": True, "drawer_id": drawer_id, "wing": wing, "room": room}
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


# ==================== KNOWLEDGE GRAPH ====================


def tool_kg_query(entity: str, as_of: str = None, direction: str = "both"):
    """Query the knowledge graph for an entity's relationships."""
    results = _kg.query_entity(entity, as_of=as_of, direction=direction)
    return {"entity": entity, "as_of": as_of, "facts": results, "count": len(results)}


def tool_kg_add(
    subject: str, predicate: str, object: str, valid_from: str = None, source_closet: str = None
):
    """Add a relationship to the knowledge graph."""
    try:
        subject = sanitize_name(subject, "subject")
        predicate = sanitize_name(predicate, "predicate")
        object = sanitize_name(object, "object")
    except ValueError as e:
        return {"success": False, "error": str(e)}

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
    return {"success": True, "triple_id": triple_id, "fact": f"{subject} → {predicate} → {object}"}


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


# ==================== AGENT DIARY ====================


def tool_diary_write(agent_name: str, entry: str, topic: str = "general"):
    """
    Write a diary entry for this agent. Each agent gets its own wing
    with a diary room. Entries are timestamped and accumulate over time.

    This is the agent's personal journal — observations, thoughts,
    what it worked on, what it noticed, what it thinks matters.
    """
    try:
        agent_name = sanitize_name(agent_name, "agent_name")
        entry = sanitize_content(entry)
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
        },
    )

    try:
        # TODO: Future versions should expand AAAK before embedding to improve
        # semantic search quality. For now, store raw AAAK in metadata so it's
        # preserved, and keep the document as-is for embedding (even though
        # compressed AAAK degrades embedding quality).
        col.add(
            ids=[entry_id],
            documents=[entry],
            metadatas=[
                {
                    "wing": wing,
                    "room": room,
                    "hall": "hall_diary",
                    "topic": topic,
                    "type": "diary_entry",
                    "agent": agent_name,
                    "filed_at": now.isoformat(),
                    "date": now.strftime("%Y-%m-%d"),
                }
            ],
        )
        logger.info(f"Diary entry: {entry_id} → {wing}/diary/{topic}")
        return {
            "success": True,
            "entry_id": entry_id,
            "agent": agent_name,
            "topic": topic,
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
        "description": "Semantic search. Returns verbatim drawer content with similarity scores. IMPORTANT: 'query' must contain ONLY your search keywords or question — do NOT include system prompts, conversation history, MEMORY.md content, or any context. Keep queries short (under 200 chars). Use 'context' for background information.",
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
        "description": "File verbatim content into the palace. Checks for duplicates first.",
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
            },
            "required": ["wing", "room", "content"],
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
    "mempalace_diary_write": {
        "description": "Write to your personal agent diary in AAAK format. Your observations, thoughts, what you worked on, what matters. Each agent has their own diary with full history. Write in AAAK for compression — e.g. 'SESSION:2026-04-04|built.palace.graph+diary.tools|ALC.req:agent.diaries.in.aaak|★★★'. Use entity codes from the AAAK spec.",
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
DEFAULT_PROTOCOL_VERSION = SUPPORTED_PROTOCOL_VERSIONS[-1]
LATEST_PROTOCOL_VERSION = SUPPORTED_PROTOCOL_VERSIONS[0]
DEFAULT_HTTP_HOST = "127.0.0.1"
DEFAULT_HTTP_PORT = 8000
DEFAULT_HTTP_PATH = "/mcp"
DEFAULT_ALLOWED_ORIGINS = (
    "https://chatgpt.com",
    "https://chat.openai.com",
)

READ_ONLY_TOOLS = {
    "mempalace_status",
    "mempalace_list_wings",
    "mempalace_list_rooms",
    "mempalace_get_taxonomy",
    "mempalace_get_aaak_spec",
    "mempalace_kg_query",
    "mempalace_kg_timeline",
    "mempalace_kg_stats",
    "mempalace_traverse",
    "mempalace_find_tunnels",
    "mempalace_graph_stats",
    "mempalace_search",
    "mempalace_check_duplicate",
    "mempalace_diary_read",
}

TOOL_ANNOTATIONS = {tool_name: {"readOnlyHint": True} for tool_name in READ_ONLY_TOOLS}
TOOL_ANNOTATIONS["mempalace_delete_drawer"] = {
    "readOnlyHint": False,
    "destructiveHint": True,
}


def _normalize_http_path(path: str) -> str:
    path = (path or DEFAULT_HTTP_PATH).strip() or DEFAULT_HTTP_PATH
    if not path.startswith("/"):
        path = f"/{path}"
    return path.rstrip("/") or "/"


def _parse_allowed_origins(values):
    items = []
    for value in values or []:
        items.extend(part.strip() for part in value.split(",") if part.strip())
    return items


def _tool_definitions():
    tools = []
    for name, spec in TOOLS.items():
        tool = {
            "name": name,
            "description": spec["description"],
            "inputSchema": spec["input_schema"],
        }
        annotations = TOOL_ANNOTATIONS.get(name)
        if annotations:
            tool["annotations"] = annotations
        tools.append(tool)
    return tools


def _jsonrpc_error(req_id, code, message, data=None):
    error = {"code": code, "message": message}
    if data is not None:
        error["data"] = data
    return {"jsonrpc": "2.0", "id": req_id, "error": error}


def _negotiate_protocol_version(params):
    requested = params.get("protocolVersion") if isinstance(params, dict) else None
    if requested is None:
        return DEFAULT_PROTOCOL_VERSION
    if requested in SUPPORTED_PROTOCOL_VERSIONS:
        return requested
    return LATEST_PROTOCOL_VERSION


def _validate_http_protocol_header(protocol_header):
    if protocol_header is None:
        return DEFAULT_PROTOCOL_VERSION, None
    if protocol_header in SUPPORTED_PROTOCOL_VERSIONS:
        return protocol_header, None
    return None, (
        HTTPStatus.BAD_REQUEST,
        _jsonrpc_error(
            None,
            -32602,
            f"Unsupported protocol version: {protocol_header}",
            {"supported": list(SUPPORTED_PROTOCOL_VERSIONS)},
        ),
    )


def _message_kind(message):
    if not isinstance(message, dict):
        return "invalid"
    if "method" in message:
        return "request" if "id" in message else "notification"
    if "result" in message or "error" in message:
        return "response"
    return "invalid"


def _payload_contains_requests(payload):
    if isinstance(payload, list):
        return any(_message_kind(item) == "request" for item in payload)
    return _message_kind(payload) == "request"


def _tool_result_is_error(result):
    if not isinstance(result, dict):
        return False
    if result.get("success") is False:
        return True
    return "error" in result


def _response_contains_errors(response):
    if isinstance(response, dict):
        return "error" in response
    if isinstance(response, list):
        return any(isinstance(item, dict) and "error" in item for item in response)
    return False


def _coerce_tool_arguments(tool_name, tool_args):
    # MCP JSON transport may deliver integers as floats or strings;
    # ChromaDB and Python slicing require native ints/floats.
    schema_props = TOOLS[tool_name]["input_schema"].get("properties", {})
    coerced = dict(tool_args)
    for key, value in list(coerced.items()):
        prop_schema = schema_props.get(key, {})
        declared_type = prop_schema.get("type")
        if declared_type == "integer" and not isinstance(value, int):
            coerced[key] = int(value)
        elif declared_type == "number" and not isinstance(value, (int, float)):
            coerced[key] = float(value)
    return coerced


def handle_request(request):
    if not isinstance(request, dict):
        return _jsonrpc_error(None, -32600, "Invalid Request")

    method = request.get("method", "")
    params = request.get("params", {})
    req_id = request.get("id")

    if method == "initialize":
        protocol_version = _negotiate_protocol_version(params)
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": protocol_version,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "mempalace", "version": __version__},
            },
        }

    if method == "notifications/initialized":
        return None

    if method == "ping":
        return {"jsonrpc": "2.0", "id": req_id, "result": {}}

    if not isinstance(params, dict):
        return _jsonrpc_error(req_id, -32602, "Invalid params")

    if method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "tools": _tool_definitions(),
            },
        }

    if method == "tools/call":
        tool_name = params.get("name")
        tool_args = params.get("arguments")
        if tool_name not in TOOLS:
            return _jsonrpc_error(req_id, -32601, f"Unknown tool: {tool_name}")
        if tool_args is None:
            tool_args = {}
        if not isinstance(tool_args, dict):
            return _jsonrpc_error(req_id, -32602, "Tool arguments must be an object")
        try:
            tool_args = _coerce_tool_arguments(tool_name, tool_args)
            result = TOOLS[tool_name]["handler"](**tool_args)
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [{"type": "text", "text": json.dumps(result, indent=2)}],
                    "isError": _tool_result_is_error(result),
                },
            }
        except (TypeError, ValueError) as exc:
            return _jsonrpc_error(req_id, -32602, f"Invalid arguments for {tool_name}: {exc}")
        except Exception:
            logger.exception("Tool error in %s", tool_name)
            return _jsonrpc_error(req_id, -32000, "Internal tool error")

    return _jsonrpc_error(req_id, -32601, f"Unknown method: {method}")


def handle_jsonrpc_payload(payload):
    if isinstance(payload, list):
        if not payload:
            return _jsonrpc_error(None, -32600, "Invalid Request")
        responses = []
        for item in payload:
            response = handle_request(item)
            if response is not None:
                responses.append(response)
        return responses or None
    return handle_request(payload)


def run_stdio_server():
    logger.info("MemPalace MCP Server starting over stdio...")
    while True:
        try:
            line = sys.stdin.readline()
            if not line:
                break
            line = line.strip()
            if not line:
                continue
            response = handle_jsonrpc_payload(json.loads(line))
            if response is not None:
                sys.stdout.write(json.dumps(response) + "\n")
                sys.stdout.flush()
        except KeyboardInterrupt:
            break
        except Exception as exc:
            logger.error(f"Server error: {exc}")


class StreamableMCPHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, server_address, request_handler_cls, endpoint_path, allowed_origins):
        super().__init__(server_address, request_handler_cls)
        self.endpoint_path = _normalize_http_path(endpoint_path)
        self.allowed_origins = set(allowed_origins or [])


class StreamableMCPRequestHandler(BaseHTTPRequestHandler):
    server_version = "MemPalaceMCP/1.0"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):  # pragma: no cover - routed to logger
        logger.info("%s - %s", self.address_string(), fmt % args)

    def _request_path(self):
        return urlsplit(self.path).path

    def _matches_endpoint(self):
        return self._request_path() == self.server.endpoint_path

    def _origin_allowed(self):
        origin = self.headers.get("Origin")
        if not origin:
            return True
        allowed = getattr(self.server, "allowed_origins", set())
        return "*" in allowed or origin in allowed

    def _send_common_headers(self, content_type=None, content_length=None, protocol_version=None):
        origin = self.headers.get("Origin")
        allowed = getattr(self.server, "allowed_origins", set())
        if origin and ("*" in allowed or origin in allowed):
            self.send_header("Access-Control-Allow-Origin", origin if "*" not in allowed else "*")
            self.send_header("Vary", "Origin")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Allow", "GET, POST, DELETE, OPTIONS")
        if content_type:
            self.send_header("Content-Type", content_type)
        if content_length is not None:
            self.send_header("Content-Length", str(content_length))
        if protocol_version:
            self.send_header("MCP-Protocol-Version", protocol_version)

    def _send_bytes(
        self, status, body=b"", content_type="text/plain; charset=utf-8", protocol=None
    ):
        self.send_response(status)
        self._send_common_headers(
            content_type=content_type,
            content_length=len(body),
            protocol_version=protocol,
        )
        self.end_headers()
        if body:
            self.wfile.write(body)

    def _send_json(self, status, payload, protocol=None):
        body = json.dumps(payload).encode("utf-8")
        self._send_bytes(status, body=body, content_type="application/json", protocol=protocol)

    def _reject_if_needed(self):
        if not self._matches_endpoint():
            self._send_bytes(HTTPStatus.NOT_FOUND, b"Not found\n")
            return True
        if not self._origin_allowed():
            self._send_bytes(HTTPStatus.FORBIDDEN, b"Origin not allowed\n")
            return True
        return False

    def do_OPTIONS(self):  # pragma: no cover - exercised indirectly by clients
        if self._reject_if_needed():
            return
        self.send_response(HTTPStatus.NO_CONTENT)
        self._send_common_headers()
        self.send_header(
            "Access-Control-Allow-Headers",
            "Content-Type, Accept, Mcp-Session-Id, MCP-Protocol-Version",
        )
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Max-Age", "600")
        self.end_headers()

    def do_GET(self):
        if self._reject_if_needed():
            return
        protocol_header = self.headers.get("MCP-Protocol-Version")
        negotiated_protocol, error = _validate_http_protocol_header(protocol_header)
        if error:
            status, payload = error
            self._send_json(status, payload, protocol=DEFAULT_PROTOCOL_VERSION)
            return
        self._send_bytes(
            HTTPStatus.METHOD_NOT_ALLOWED,
            b"SSE stream not implemented\n",
            protocol=negotiated_protocol,
        )

    def do_DELETE(self):
        if self._reject_if_needed():
            return
        protocol_header = self.headers.get("MCP-Protocol-Version")
        negotiated_protocol, error = _validate_http_protocol_header(protocol_header)
        if error:
            status, payload = error
            self._send_json(status, payload, protocol=DEFAULT_PROTOCOL_VERSION)
            return
        self._send_bytes(
            HTTPStatus.METHOD_NOT_ALLOWED,
            b"Session deletion is not supported\n",
            protocol=negotiated_protocol,
        )

    def do_POST(self):
        if self._reject_if_needed():
            return

        protocol_header = self.headers.get("MCP-Protocol-Version")

        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._send_bytes(HTTPStatus.BAD_REQUEST, b"Invalid Content-Length\n")
            return

        raw_body = self.rfile.read(content_length)

        try:
            payload = json.loads(raw_body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._send_bytes(HTTPStatus.BAD_REQUEST, b"Invalid JSON body\n")
            return

        negotiated_protocol, error = _validate_http_protocol_header(protocol_header)
        if error:
            status, payload = error
            self._send_json(status, payload, protocol=DEFAULT_PROTOCOL_VERSION)
            return

        response = handle_jsonrpc_payload(payload)
        response_protocol = negotiated_protocol
        if isinstance(response, dict):
            result = response.get("result", {})
            if isinstance(result, dict) and "protocolVersion" in result:
                response_protocol = result["protocolVersion"]

        if not _payload_contains_requests(payload):
            if response is not None and _response_contains_errors(response):
                self._send_json(HTTPStatus.BAD_REQUEST, response, protocol=response_protocol)
                return
            self._send_bytes(HTTPStatus.ACCEPTED, protocol=response_protocol)
            return

        if response is None:
            self._send_bytes(HTTPStatus.ACCEPTED, protocol=response_protocol)
            return

        self._send_json(HTTPStatus.OK, response, protocol=response_protocol)


def build_http_server(
    host=DEFAULT_HTTP_HOST, port=DEFAULT_HTTP_PORT, path=DEFAULT_HTTP_PATH, allowed_origins=None
):
    return StreamableMCPHTTPServer(
        (host, port),
        StreamableMCPRequestHandler,
        endpoint_path=path,
        allowed_origins=allowed_origins,
    )


def run_streamable_http_server(
    host=DEFAULT_HTTP_HOST, port=DEFAULT_HTTP_PORT, path=DEFAULT_HTTP_PATH, allowed_origins=None
):
    server = build_http_server(host=host, port=port, path=path, allowed_origins=allowed_origins)
    logger.info(
        "MemPalace MCP Server starting over streamable HTTP at http://%s:%s%s",
        host,
        port,
        server.endpoint_path,
    )
    logger.info(
        "Allowed origins: %s",
        ", ".join(sorted(server.allowed_origins))
        if server.allowed_origins
        else "(none configured)",
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Run the MemPalace MCP server.")
    parser.add_argument(
        "--palace",
        metavar="PATH",
        default=_args.palace,
        help="Path to the palace directory (overrides config file and env var).",
    )
    parser.add_argument(
        "--transport",
        choices=["stdio", "streamable-http"],
        default=os.environ.get("MEMPALACE_MCP_TRANSPORT", "stdio"),
        help="MCP transport to expose (default: stdio).",
    )
    parser.add_argument(
        "--host",
        default=os.environ.get("MEMPALACE_MCP_HOST", DEFAULT_HTTP_HOST),
        help="HTTP bind host for streamable-http transport.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("MEMPALACE_MCP_PORT", DEFAULT_HTTP_PORT)),
        help="HTTP bind port for streamable-http transport.",
    )
    parser.add_argument(
        "--path",
        default=os.environ.get("MEMPALACE_MCP_PATH", DEFAULT_HTTP_PATH),
        help="Endpoint path for streamable-http transport (default: /mcp).",
    )
    parser.add_argument(
        "--allow-origin",
        action="append",
        default=[],
        help="Allowed Origin header value for HTTP requests. Repeat or pass comma-separated values.",
    )
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    if args.transport == "stdio":
        run_stdio_server()
        return

    configured_origins = _parse_allowed_origins(args.allow_origin)
    env_origins = _parse_allowed_origins([os.environ.get("MEMPALACE_ALLOWED_ORIGINS", "")])
    allowed_origins = configured_origins or env_origins or list(DEFAULT_ALLOWED_ORIGINS)
    run_streamable_http_server(
        host=args.host,
        port=args.port,
        path=args.path,
        allowed_origins=allowed_origins,
    )


if __name__ == "__main__":
    main()
