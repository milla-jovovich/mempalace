#!/usr/bin/env python3
"""
palace-helper.py — CLI wrapper for MemPalace, designed for Taurus agents.

Lets agents interact with MemPalace through the Bash tool using simple
subcommands instead of writing Python boilerplate each time.

Output is JSON by default (easy for agents to parse). Use --human for
human-readable formatted output.

Usage:
    python palace-helper.py search "climate CO2 correlation" --limit 5
    python palace-helper.py store research climate "CO2 acceleration r=0.932"
    python palace-helper.py kg-add CO2 correlates_with temperature --valid-from 2026-04-11
    python palace-helper.py status
    python palace-helper.py diary-write my-agent "Completed climate analysis"

Environment:
    MEMPALACE_PATH — Palace directory (default: /shared/palace)
"""

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Palace path resolution
# ---------------------------------------------------------------------------

def _palace_path() -> str:
    """Resolve palace path from env or default."""
    return os.environ.get("MEMPALACE_PATH",
           os.environ.get("MEMPALACE_PALACE_PATH", "/shared/palace"))

# ---------------------------------------------------------------------------
# Embedded KG shim — used when mempalace package is not installed.
# Mirrors the mempalace.knowledge_graph.KnowledgeGraph API using raw SQLite.
# ---------------------------------------------------------------------------

class _EmbeddedKG:
    """Minimal KnowledgeGraph using raw SQLite — no mempalace dependency."""

    def __init__(self, db_path: str):
        import sqlite3
        self._db_path = db_path
        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
        self._conn = sqlite3.connect(db_path)
        self._conn.row_factory = sqlite3.Row
        self._init_db()

    def _init_db(self):
        c = self._conn
        c.execute("""CREATE TABLE IF NOT EXISTS entities (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            created_at TEXT DEFAULT (datetime('now'))
        )""")
        c.execute("""CREATE TABLE IF NOT EXISTS triples (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            subject TEXT NOT NULL,
            predicate TEXT NOT NULL,
            object TEXT NOT NULL,
            valid_from TEXT,
            valid_to TEXT,
            source_closet TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now'))
        )""")
        c.execute("CREATE INDEX IF NOT EXISTS idx_triples_subject ON triples(subject)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_triples_object ON triples(object)")
        c.commit()

    def _ensure_entity(self, name: str):
        try:
            self._conn.execute("INSERT OR IGNORE INTO entities(name) VALUES(?)", (name,))
            self._conn.commit()
        except Exception:
            pass

    def add_triple(self, subject, predicate, obj, valid_from=None, source_closet=""):
        self._ensure_entity(subject)
        self._ensure_entity(obj)
        self._conn.execute(
            "INSERT INTO triples(subject, predicate, object, valid_from, source_closet) VALUES(?,?,?,?,?)",
            (subject, predicate, obj, valid_from, source_closet))
        self._conn.commit()

    def invalidate(self, subject, predicate, obj, ended=None):
        ended = ended or datetime.now().strftime("%Y-%m-%d")
        self._conn.execute(
            "UPDATE triples SET valid_to=? WHERE subject=? AND predicate=? AND object=? AND valid_to IS NULL",
            (ended, subject, predicate, obj))
        self._conn.commit()

    def query_entity(self, entity, as_of=None, direction="both"):
        rows = []
        if direction in ("both", "outgoing"):
            cur = self._conn.execute(
                "SELECT subject,predicate,object,valid_from,valid_to FROM triples WHERE subject=?", (entity,))
            rows.extend([dict(r) for r in cur.fetchall()])
        if direction in ("both", "incoming"):
            cur = self._conn.execute(
                "SELECT subject,predicate,object,valid_from,valid_to FROM triples WHERE object=?", (entity,))
            rows.extend([dict(r) for r in cur.fetchall()])
        if as_of:
            rows = [r for r in rows
                    if (not r["valid_from"] or r["valid_from"] <= as_of)
                    and (not r["valid_to"] or r["valid_to"] > as_of)]
        return rows

    def timeline(self, entity=None):
        if entity:
            cur = self._conn.execute(
                "SELECT * FROM triples WHERE subject=? OR object=? ORDER BY COALESCE(valid_from, created_at)",
                (entity, entity))
        else:
            cur = self._conn.execute(
                "SELECT * FROM triples ORDER BY COALESCE(valid_from, created_at)")
        return [dict(r) for r in cur.fetchall()]

    def stats(self):
        entities = self._conn.execute("SELECT COUNT(*) FROM entities").fetchone()[0]
        triples = self._conn.execute("SELECT COUNT(*) FROM triples").fetchone()[0]
        active = self._conn.execute("SELECT COUNT(*) FROM triples WHERE valid_to IS NULL").fetchone()[0]
        preds = self._conn.execute("SELECT DISTINCT predicate FROM triples").fetchall()
        return {
            "entities": entities, "triples": triples,
            "active_triples": active,
            "relationship_types": [r[0] for r in preds],
        }

    def close(self):
        self._conn.close()


# ---------------------------------------------------------------------------
# Lazy imports — ChromaDB and KnowledgeGraph are heavy; import on first use.
# ---------------------------------------------------------------------------

_client_cache = None
_collection_cache = None
_kg_cache = None


def _get_client(palace_path: str = None):
    global _client_cache
    if _client_cache is None:
        import chromadb
        _client_cache = chromadb.PersistentClient(path=palace_path or _palace_path())
    return _client_cache


def _get_collection(palace_path: str = None, create: bool = False):
    global _collection_cache
    if _collection_cache is None:
        client = _get_client(palace_path)
        collection_name = "mempalace_drawers"
        if create:
            _collection_cache = client.get_or_create_collection(collection_name)
        else:
            try:
                _collection_cache = client.get_collection(collection_name)
            except Exception:
                if create:
                    _collection_cache = client.get_or_create_collection(collection_name)
                else:
                    return None
    return _collection_cache


def _get_kg(palace_path: str = None):
    global _kg_cache
    if _kg_cache is None:
        pp = palace_path or _palace_path()
        db_path = os.path.join(pp, "knowledge_graph.sqlite3")
        try:
            from mempalace.knowledge_graph import KnowledgeGraph
        except ImportError:
            # Fallback: add MemPalace source to path if cloned locally
            for candidate in ["/shared/mempalace", "/shared/mempalace/mempalace"]:
                parent = os.path.dirname(candidate) if candidate.endswith("mempalace") else candidate
                if os.path.isfile(os.path.join(candidate, "knowledge_graph.py")):
                    sys.path.insert(0, parent)
                    break
            try:
                from mempalace.knowledge_graph import KnowledgeGraph
            except ImportError:
                # Last resort: use the embedded KG shim
                KnowledgeGraph = _EmbeddedKG
        _kg_cache = KnowledgeGraph(db_path=db_path)
    return _kg_cache


# ---------------------------------------------------------------------------
# Output formatting
# ---------------------------------------------------------------------------

def _output(data, human: bool = False):
    """Print result as JSON or human-readable text."""
    if human:
        _print_human(data)
    else:
        print(json.dumps(data, indent=2, default=str))


def _print_human(data):
    """Pretty-print a result dict for human reading."""
    if isinstance(data, list):
        for item in data:
            _print_human(item)
            print()
        return
    if not isinstance(data, dict):
        print(data)
        return
    # Error handling
    if "error" in data:
        print(f"ERROR: {data['error']}")
        if "hint" in data:
            print(f"  Hint: {data['hint']}")
        return
    # Generic dict printing
    for k, v in data.items():
        if isinstance(v, dict):
            print(f"{k}:")
            for k2, v2 in v.items():
                print(f"  {k2}: {v2}")
        elif isinstance(v, list) and v and isinstance(v[0], dict):
            print(f"{k}:")
            for i, item in enumerate(v, 1):
                parts = []
                for ik, iv in item.items():
                    parts.append(f"{ik}={iv}")
                print(f"  [{i}] {', '.join(parts)}")
        else:
            print(f"{k}: {v}")


# ---------------------------------------------------------------------------
# Subcommand implementations
# ---------------------------------------------------------------------------

def cmd_status(args):
    """Palace overview: total drawers, wings, rooms."""
    col = _get_collection(args.palace)
    if not col:
        return {"error": "No palace found", "hint": f"Run: python palace-init.py --path {args.palace or _palace_path()}"}
    count = col.count()
    wings = {}
    rooms = {}
    try:
        all_meta = col.get(include=["metadatas"], limit=10000)["metadatas"]
        for m in all_meta:
            w = m.get("wing", "unknown")
            r = m.get("room", "unknown")
            wings[w] = wings.get(w, 0) + 1
            rooms[r] = rooms.get(r, 0) + 1
    except Exception:
        pass
    return {"total_drawers": count, "wings": wings, "rooms": rooms,
            "palace_path": args.palace or _palace_path()}


def cmd_search(args):
    """Semantic search across all memories."""
    col = _get_collection(args.palace)
    if not col:
        return {"error": "No palace found", "hint": "Run palace-init.py first"}

    query = args.query
    wing = args.wing
    room = args.room
    n_results = args.limit

    # Build where filter
    where = {}
    if wing and room:
        where = {"$and": [{"wing": wing}, {"room": room}]}
    elif wing:
        where = {"wing": wing}
    elif room:
        where = {"room": room}

    kwargs = {
        "query_texts": [query],
        "n_results": n_results,
        "include": ["documents", "metadatas", "distances"],
    }
    if where:
        kwargs["where"] = where

    try:
        results = col.query(**kwargs)
    except Exception as e:
        return {"error": f"Search error: {e}"}

    docs = results["documents"][0] if results["documents"] else []
    metas = results["metadatas"][0] if results["metadatas"] else []
    dists = results["distances"][0] if results["distances"] else []

    hits = []
    for doc, meta, dist in zip(docs, metas, dists):
        hits.append({
            "text": doc,
            "wing": meta.get("wing", "unknown"),
            "room": meta.get("room", "unknown"),
            "source_file": Path(meta.get("source_file", "?")).name,
            "similarity": round(1 - dist, 3),
        })

    return {"query": query, "filters": {"wing": wing, "room": room}, "results": hits}


def cmd_store(args):
    """Store content into a wing/room (add a drawer)."""
    col = _get_collection(args.palace, create=True)
    if not col:
        return {"error": "Could not access palace"}
    wing = args.wing
    room = args.room
    content = args.content
    source = args.source or ""
    drawer_id = (
        f"drawer_{wing}_{room}_"
        f"{hashlib.sha256((wing + room + content[:100]).encode()).hexdigest()[:24]}"
    )
    # Idempotency check
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
            metadatas=[{
                "wing": wing, "room": room,
                "source_file": source, "chunk_index": 0,
                "added_by": "palace-helper",
                "filed_at": datetime.now().isoformat(),
            }],
        )
        return {"success": True, "drawer_id": drawer_id, "wing": wing, "room": room}
    except Exception as e:
        return {"success": False, "error": str(e)}


def cmd_delete(args):
    """Delete a drawer by ID."""
    col = _get_collection(args.palace)
    if not col:
        return {"error": "No palace found"}
    try:
        existing = col.get(ids=[args.drawer_id])
        if not existing["ids"]:
            return {"success": False, "error": f"Drawer not found: {args.drawer_id}"}
        col.delete(ids=[args.drawer_id])
        return {"success": True, "drawer_id": args.drawer_id}
    except Exception as e:
        return {"success": False, "error": str(e)}


def cmd_check_dup(args):
    """Check if content already exists (duplicate detection)."""
    col = _get_collection(args.palace)
    if not col:
        return {"error": "No palace found"}
    threshold = args.threshold
    try:
        results = col.query(
            query_texts=[args.content], n_results=5,
            include=["metadatas", "documents", "distances"],
        )
        duplicates = []
        if results["ids"] and results["ids"][0]:
            for i, did in enumerate(results["ids"][0]):
                dist = results["distances"][0][i]
                sim = round(1 - dist, 3)
                if sim >= threshold:
                    meta = results["metadatas"][0][i]
                    doc = results["documents"][0][i]
                    duplicates.append({
                        "id": did, "wing": meta.get("wing", "?"),
                        "room": meta.get("room", "?"), "similarity": sim,
                        "content": doc[:200] + ("..." if len(doc) > 200 else ""),
                    })
        return {"is_duplicate": len(duplicates) > 0, "matches": duplicates}
    except Exception as e:
        return {"error": str(e)}


def cmd_list_wings(args):
    """List all wings with drawer counts."""
    col = _get_collection(args.palace)
    if not col:
        return {"error": "No palace found"}
    wings = {}
    try:
        all_meta = col.get(include=["metadatas"], limit=10000)["metadatas"]
        for m in all_meta:
            w = m.get("wing", "unknown")
            wings[w] = wings.get(w, 0) + 1
    except Exception:
        pass
    return {"wings": wings}


def cmd_list_rooms(args):
    """List rooms, optionally filtered by wing."""
    col = _get_collection(args.palace)
    if not col:
        return {"error": "No palace found"}
    rooms = {}
    try:
        kwargs = {"include": ["metadatas"], "limit": 10000}
        if args.wing:
            kwargs["where"] = {"wing": args.wing}
        all_meta = col.get(**kwargs)["metadatas"]
        for m in all_meta:
            r = m.get("room", "unknown")
            rooms[r] = rooms.get(r, 0) + 1
    except Exception:
        pass
    return {"wing": args.wing or "all", "rooms": rooms}


def cmd_taxonomy(args):
    """Full wing → room → count tree."""
    col = _get_collection(args.palace)
    if not col:
        return {"error": "No palace found"}
    taxonomy = {}
    try:
        all_meta = col.get(include=["metadatas"], limit=10000)["metadatas"]
        for m in all_meta:
            w = m.get("wing", "unknown")
            r = m.get("room", "unknown")
            if w not in taxonomy:
                taxonomy[w] = {}
            taxonomy[w][r] = taxonomy[w].get(r, 0) + 1
    except Exception:
        pass
    return {"taxonomy": taxonomy}


# -- Knowledge Graph commands ------------------------------------------------

def cmd_kg_query(args):
    """Query entity relationships in the knowledge graph."""
    kg = _get_kg(args.palace)
    results = kg.query_entity(args.entity, as_of=args.as_of, direction=args.direction)
    return {"entity": args.entity, "as_of": args.as_of, "facts": results, "count": len(results)}


def cmd_kg_add(args):
    """Add a relationship triple to the knowledge graph."""
    kg = _get_kg(args.palace)
    triple_id = kg.add_triple(
        args.subject, args.predicate, args.object,
        valid_from=args.valid_from, source_closet=args.source,
    )
    return {"success": True, "triple_id": triple_id,
            "fact": f"{args.subject} → {args.predicate} → {args.object}"}


def cmd_kg_invalidate(args):
    """Mark a fact as no longer true."""
    kg = _get_kg(args.palace)
    kg.invalidate(args.subject, args.predicate, args.object, ended=args.ended)
    return {"success": True,
            "fact": f"{args.subject} → {args.predicate} → {args.object}",
            "ended": args.ended or "today"}


def cmd_kg_timeline(args):
    """Chronological timeline of facts, optionally for one entity."""
    kg = _get_kg(args.palace)
    results = kg.timeline(args.entity)
    return {"entity": args.entity or "all", "timeline": results, "count": len(results)}


def cmd_kg_stats(args):
    """Knowledge graph overview: entities, triples, relationship types."""
    kg = _get_kg(args.palace)
    return kg.stats()


# -- Palace Graph commands ---------------------------------------------------

def _try_import_palace_graph():
    """Try to import palace_graph from mempalace package or cloned repo."""
    try:
        from mempalace import palace_graph
        return palace_graph
    except ImportError:
        pass
    for candidate in ["/shared/mempalace"]:
        mod_file = os.path.join(candidate, "mempalace", "palace_graph.py")
        if os.path.isfile(mod_file):
            sys.path.insert(0, candidate)
            try:
                from mempalace import palace_graph
                return palace_graph
            except ImportError:
                pass
    return None


def cmd_traverse(args):
    """Walk from a room, find connected ideas across wings."""
    pg = _try_import_palace_graph()
    if not pg:
        return {"error": "Palace graph requires mempalace package or cloned repo at /shared/mempalace"}
    col = _get_collection(args.palace)
    if not col:
        return {"error": "No palace found"}
    return pg.traverse(args.start_room, col=col, max_hops=args.max_hops)


def cmd_tunnels(args):
    """Find rooms that bridge two wings."""
    pg = _try_import_palace_graph()
    if not pg:
        return {"error": "Palace graph requires mempalace package or cloned repo at /shared/mempalace"}
    col = _get_collection(args.palace)
    if not col:
        return {"error": "No palace found"}
    return pg.find_tunnels(args.wing_a, args.wing_b, col=col)


def cmd_graph_stats(args):
    """Palace graph connectivity overview."""
    pg = _try_import_palace_graph()
    if not pg:
        return {"error": "Palace graph requires mempalace package or cloned repo at /shared/mempalace"}
    col = _get_collection(args.palace)
    if not col:
        return {"error": "No palace found"}
    return pg.graph_stats(col=col)


# -- Diary commands ----------------------------------------------------------

def cmd_diary_write(args):
    """Write a diary entry for an agent."""
    col = _get_collection(args.palace, create=True)
    if not col:
        return {"error": "Could not access palace"}
    agent = args.agent_name
    entry = args.entry
    topic = args.topic
    wing = f"wing_{agent.lower().replace(' ', '_')}"
    now = datetime.now()
    entry_id = (
        f"diary_{wing}_{now.strftime('%Y%m%d_%H%M%S')}_"
        f"{hashlib.sha256(entry[:50].encode()).hexdigest()[:12]}"
    )
    try:
        col.add(
            ids=[entry_id], documents=[entry],
            metadatas=[{
                "wing": wing, "room": "diary", "hall": "hall_diary",
                "topic": topic, "type": "diary_entry", "agent": agent,
                "filed_at": now.isoformat(), "date": now.strftime("%Y-%m-%d"),
            }],
        )
        return {"success": True, "entry_id": entry_id,
                "agent": agent, "topic": topic, "timestamp": now.isoformat()}
    except Exception as e:
        return {"success": False, "error": str(e)}


def cmd_diary_read(args):
    """Read an agent's recent diary entries."""
    col = _get_collection(args.palace)
    if not col:
        return {"error": "No palace found"}
    wing = f"wing_{args.agent_name.lower().replace(' ', '_')}"
    try:
        results = col.get(
            where={"$and": [{"wing": wing}, {"room": "diary"}]},
            include=["documents", "metadatas"], limit=10000,
        )
        if not results["ids"]:
            return {"agent": args.agent_name, "entries": [], "message": "No diary entries yet."}
        entries = []
        for doc, meta in zip(results["documents"], results["metadatas"]):
            entries.append({
                "date": meta.get("date", ""), "timestamp": meta.get("filed_at", ""),
                "topic": meta.get("topic", ""), "content": doc,
            })
        entries.sort(key=lambda x: x["timestamp"], reverse=True)
        entries = entries[:args.last_n]
        return {"agent": args.agent_name, "entries": entries,
                "total": len(results["ids"]), "showing": len(entries)}
    except Exception as e:
        return {"error": str(e)}


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="palace-helper",
        description="CLI wrapper for MemPalace — designed for Taurus agents.",
        epilog="Set MEMPALACE_PATH to change palace location (default: /shared/palace).",
    )
    p.add_argument("--palace", metavar="PATH", default=None,
                   help="Palace path (overrides MEMPALACE_PATH env var)")
    p.add_argument("--human", action="store_true",
                   help="Human-readable output instead of JSON")

    sub = p.add_subparsers(dest="command", help="Available commands")

    # -- status --
    sp = sub.add_parser("status", help="Palace overview: drawers, wings, rooms")
    sp.set_defaults(func=cmd_status)

    # -- search --
    sp = sub.add_parser("search", help="Semantic search across all memories")
    sp.add_argument("query", help="Natural-language search query")
    sp.add_argument("--wing", help="Filter by wing")
    sp.add_argument("--room", help="Filter by room")
    sp.add_argument("--limit", type=int, default=5, help="Max results (default 5)")
    sp.set_defaults(func=cmd_search)

    # -- store --
    sp = sub.add_parser("store", help="Store content into a wing/room")
    sp.add_argument("wing", help="Wing name (e.g. research, projects)")
    sp.add_argument("room", help="Room name (e.g. climate, economics)")
    sp.add_argument("content", help="Content to store")
    sp.add_argument("--source", help="Source file reference")
    sp.set_defaults(func=cmd_store)

    # -- delete --
    sp = sub.add_parser("delete", help="Delete a drawer by ID")
    sp.add_argument("drawer_id", help="Drawer ID to delete")
    sp.set_defaults(func=cmd_delete)

    # -- check-dup --
    sp = sub.add_parser("check-dup", help="Check if content is a duplicate")
    sp.add_argument("content", help="Content to check")
    sp.add_argument("--threshold", type=float, default=0.87,
                    help="Similarity threshold (default 0.87)")
    sp.set_defaults(func=cmd_check_dup)

    # -- list-wings --
    sp = sub.add_parser("list-wings", help="List all wings with drawer counts")
    sp.set_defaults(func=cmd_list_wings)

    # -- list-rooms --
    sp = sub.add_parser("list-rooms", help="List rooms (optionally in a wing)")
    sp.add_argument("--wing", help="Filter by wing")
    sp.set_defaults(func=cmd_list_rooms)

    # -- taxonomy --
    sp = sub.add_parser("taxonomy", help="Full wing → room → count tree")
    sp.set_defaults(func=cmd_taxonomy)

    # -- kg-query --
    sp = sub.add_parser("kg-query", help="Query entity relationships")
    sp.add_argument("entity", help="Entity name to query")
    sp.add_argument("--as-of", dest="as_of", help="Date filter (YYYY-MM-DD)")
    sp.add_argument("--direction", default="both",
                    choices=["outgoing", "incoming", "both"],
                    help="Relationship direction (default: both)")
    sp.set_defaults(func=cmd_kg_query)

    # -- kg-add --
    sp = sub.add_parser("kg-add", help="Add a fact (subject → predicate → object)")
    sp.add_argument("subject", help="Subject entity")
    sp.add_argument("predicate", help="Relationship type")
    sp.add_argument("object", help="Object entity")
    sp.add_argument("--valid-from", dest="valid_from", help="When fact became true")
    sp.add_argument("--source", help="Source reference")
    sp.set_defaults(func=cmd_kg_add)

    # -- kg-invalidate --
    sp = sub.add_parser("kg-invalidate", help="Mark a fact as no longer true")
    sp.add_argument("subject", help="Subject entity")
    sp.add_argument("predicate", help="Relationship type")
    sp.add_argument("object", help="Object entity")
    sp.add_argument("--ended", help="When it stopped being true (default: today)")
    sp.set_defaults(func=cmd_kg_invalidate)

    # -- kg-timeline --
    sp = sub.add_parser("kg-timeline", help="Chronological fact timeline")
    sp.add_argument("entity", nargs="?", default=None,
                    help="Entity to filter (omit for all)")
    sp.set_defaults(func=cmd_kg_timeline)

    # -- kg-stats --
    sp = sub.add_parser("kg-stats", help="Knowledge graph overview")
    sp.set_defaults(func=cmd_kg_stats)

    # -- traverse --
    sp = sub.add_parser("traverse", help="Walk from a room across wings")
    sp.add_argument("start_room", help="Room to start from")
    sp.add_argument("--max-hops", dest="max_hops", type=int, default=2,
                    help="Max traversal depth (default 2)")
    sp.set_defaults(func=cmd_traverse)

    # -- tunnels --
    sp = sub.add_parser("tunnels", help="Find rooms bridging two wings")
    sp.add_argument("wing_a", nargs="?", default=None, help="First wing")
    sp.add_argument("wing_b", nargs="?", default=None, help="Second wing")
    sp.set_defaults(func=cmd_tunnels)

    # -- graph-stats --
    sp = sub.add_parser("graph-stats", help="Palace graph connectivity overview")
    sp.set_defaults(func=cmd_graph_stats)

    # -- diary-write --
    sp = sub.add_parser("diary-write", help="Write a diary entry")
    sp.add_argument("agent_name", help="Agent name / identifier")
    sp.add_argument("entry", help="Diary entry text")
    sp.add_argument("--topic", default="general", help="Topic tag (default: general)")
    sp.set_defaults(func=cmd_diary_write)

    # -- diary-read --
    sp = sub.add_parser("diary-read", help="Read recent diary entries")
    sp.add_argument("agent_name", help="Agent name")
    sp.add_argument("--last-n", dest="last_n", type=int, default=10,
                    help="Number of entries (default 10)")
    sp.set_defaults(func=cmd_diary_read)

    return p


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = build_parser()
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    try:
        result = args.func(args)
        _output(result, human=args.human)
    except Exception as e:
        err = {"error": str(e), "type": type(e).__name__}
        _output(err, human=args.human)
        sys.exit(1)


if __name__ == "__main__":
    main()
