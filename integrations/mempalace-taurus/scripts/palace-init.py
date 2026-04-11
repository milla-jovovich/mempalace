#!/usr/bin/env python3
"""
palace-init.py — One-time palace initialization for Taurus agents.

Creates a palace directory with default wings & rooms, initialises ChromaDB
and the knowledge-graph SQLite database.

Usage:
    python palace-init.py                        # use MEMPALACE_PATH or /shared/palace
    python palace-init.py --shared               # explicit /shared/palace
    python palace-init.py --private              # explicit /workspace/palace
    python palace-init.py --path /custom/path
    python palace-init.py --wings research,projects,people
    python palace-init.py --import-dir ./notes   # import markdown files
"""

import argparse
import glob
import hashlib
import json
import os
import sys
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

DEFAULT_WINGS = {
    "wing_research": {
        "description": "Research domains and scientific findings",
        "rooms": ["climate", "economics", "astrophysics", "epidemiology", "general"],
    },
    "wing_projects": {
        "description": "Active projects and engineering work",
        "rooms": ["current", "archive", "planning"],
    },
    "wing_people": {
        "description": "People, organisations, and relationships",
        "rooms": ["contacts", "teams", "organisations"],
    },
    "wing_agent": {
        "description": "Agent self-knowledge, diaries, and meta-observations",
        "rooms": ["diary", "observations", "decisions"],
    },
}


def resolve_path(args) -> str:
    """Determine palace path from flags, env, or default."""
    if args.path:
        return os.path.abspath(args.path)
    if args.shared:
        return "/shared/palace"
    if args.private:
        return "/workspace/palace"
    return os.environ.get("MEMPALACE_PATH",
           os.environ.get("MEMPALACE_PALACE_PATH", "/shared/palace"))


def parse_custom_wings(wing_str: str) -> dict:
    """Parse --wings flag: comma-separated names → default rooms each."""
    wings = {}
    for name in wing_str.split(","):
        name = name.strip()
        if not name:
            continue
        key = name if name.startswith("wing_") else f"wing_{name}"
        wings[key] = {
            "description": f"{name.replace('wing_', '').replace('_', ' ').title()} wing",
            "rooms": ["general"],
        }
    return wings


def init_palace(palace_path: str, wings: dict, verbose: bool = True):
    """Create palace directory, ChromaDB collection, and KG database."""

    pp = Path(palace_path)
    pp.mkdir(parents=True, exist_ok=True)

    created = {"path": str(pp), "wings": {}, "chromadb": False, "kg": False}

    # --- ChromaDB collection ---
    try:
        import chromadb
        client = chromadb.PersistentClient(path=palace_path)
        col = client.get_or_create_collection("mempalace_drawers")
        created["chromadb"] = True
        if verbose:
            print(f"✓ ChromaDB collection 'mempalace_drawers' ready ({col.count()} drawers)")
    except Exception as e:
        if verbose:
            print(f"✗ ChromaDB init failed: {e}")

    # --- Seed wing/room structure as a marker drawer per room ---
    try:
        col = client.get_or_create_collection("mempalace_drawers")
        now = datetime.now().isoformat()
        ids, docs, metas = [], [], []
        for wing_name, wing_info in wings.items():
            created["wings"][wing_name] = []
            for room in wing_info.get("rooms", ["general"]):
                marker_id = f"marker_{wing_name}_{room}"
                # Only add if not already present
                try:
                    existing = col.get(ids=[marker_id])
                    if existing and existing["ids"]:
                        created["wings"][wing_name].append(room)
                        continue
                except Exception:
                    pass
                ids.append(marker_id)
                docs.append(
                    f"[Palace structure] Wing: {wing_name}, Room: {room}. "
                    f"{wing_info.get('description', '')}"
                )
                metas.append({
                    "wing": wing_name, "room": room,
                    "type": "structure_marker",
                    "added_by": "palace-init",
                    "filed_at": now,
                })
                created["wings"][wing_name].append(room)
        if ids:
            col.add(ids=ids, documents=docs, metadatas=metas)
            if verbose:
                print(f"✓ Created {len(ids)} room markers across {len(wings)} wings")
        else:
            if verbose:
                print(f"✓ All {sum(len(r) for r in created['wings'].values())} rooms already exist")
    except Exception as e:
        if verbose:
            print(f"✗ Room marker seeding failed: {e}")

    # --- Knowledge graph SQLite ---
    try:
        from mempalace.knowledge_graph import KnowledgeGraph
        kg_path = os.path.join(palace_path, "knowledge_graph.sqlite3")
        kg = KnowledgeGraph(db_path=kg_path)
        stats = kg.stats()
        created["kg"] = True
        kg.close()
        if verbose:
            print(f"✓ Knowledge graph ready ({stats['entities']} entities, {stats['triples']} triples)")
    except ImportError:
        # KG module not available — create minimal SQLite structure
        try:
            import sqlite3
            kg_path = os.path.join(palace_path, "knowledge_graph.sqlite3")
            conn = sqlite3.connect(kg_path)
            conn.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS entities (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL,
                    type TEXT DEFAULT 'unknown', properties TEXT DEFAULT '{}',
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS triples (
                    id TEXT PRIMARY KEY, subject TEXT NOT NULL,
                    predicate TEXT NOT NULL, object TEXT NOT NULL,
                    valid_from TEXT, valid_to TEXT,
                    confidence REAL DEFAULT 1.0,
                    source_closet TEXT, source_file TEXT,
                    extracted_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (subject) REFERENCES entities(id),
                    FOREIGN KEY (object) REFERENCES entities(id)
                );
                CREATE INDEX IF NOT EXISTS idx_triples_subject ON triples(subject);
                CREATE INDEX IF NOT EXISTS idx_triples_object ON triples(object);
                CREATE INDEX IF NOT EXISTS idx_triples_predicate ON triples(predicate);
            """)
            conn.commit()
            conn.close()
            created["kg"] = True
            if verbose:
                print(f"✓ Knowledge graph SQLite initialised (mempalace library not found, manual init)")
        except Exception as e2:
            if verbose:
                print(f"✗ Knowledge graph init failed: {e2}")
    except Exception as e:
        if verbose:
            print(f"✗ Knowledge graph init failed: {e}")

    return created


def import_markdown_files(palace_path: str, import_dir: str, verbose: bool = True):
    """Import .md files from a directory into the palace."""
    import chromadb

    md_files = glob.glob(os.path.join(import_dir, "**/*.md"), recursive=True)
    if not md_files:
        if verbose:
            print(f"No markdown files found in {import_dir}")
        return 0

    client = chromadb.PersistentClient(path=palace_path)
    col = client.get_or_create_collection("mempalace_drawers")
    now = datetime.now().isoformat()
    imported = 0

    for fpath in md_files:
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                content = f.read().strip()
            if not content:
                continue
            # Derive wing/room from directory structure
            rel = os.path.relpath(fpath, import_dir)
            parts = Path(rel).parts
            wing = f"wing_{parts[0]}" if len(parts) > 1 else "wing_imported"
            room = parts[1].replace(".md", "") if len(parts) > 2 else Path(parts[-1]).stem

            drawer_id = (
                f"drawer_{wing}_{room}_"
                f"{hashlib.sha256((wing + room + content[:100]).encode()).hexdigest()[:24]}"
            )
            col.upsert(
                ids=[drawer_id], documents=[content],
                metadatas=[{
                    "wing": wing, "room": room,
                    "source_file": os.path.basename(fpath),
                    "added_by": "palace-init-import",
                    "filed_at": now, "chunk_index": 0,
                }],
            )
            imported += 1
        except Exception as e:
            if verbose:
                print(f"  Warning: Could not import {fpath}: {e}")

    if verbose:
        print(f"✓ Imported {imported} markdown files from {import_dir}")
    return imported


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        prog="palace-init",
        description="Initialise a MemPalace with default wings and rooms.",
    )
    loc = parser.add_mutually_exclusive_group()
    loc.add_argument("--shared", action="store_true",
                     help="Create palace at /shared/palace (multi-agent)")
    loc.add_argument("--private", action="store_true",
                     help="Create palace at /workspace/palace (single-agent)")
    loc.add_argument("--path", metavar="DIR",
                     help="Custom palace path")
    parser.add_argument("--wings", metavar="LIST",
                        help="Comma-separated wing names (overrides defaults)")
    parser.add_argument("--import-dir", metavar="DIR",
                        help="Import markdown files from this directory")
    parser.add_argument("--json", action="store_true",
                        help="Output results as JSON")
    args = parser.parse_args()

    palace_path = resolve_path(args)
    wings = parse_custom_wings(args.wings) if args.wings else DEFAULT_WINGS
    verbose = not args.json

    if verbose:
        print(f"Initialising MemPalace at: {palace_path}")
        print(f"Wings: {', '.join(wings.keys())}")
        print()

    result = init_palace(palace_path, wings, verbose=verbose)

    if args.import_dir:
        result["imported"] = import_markdown_files(palace_path, args.import_dir, verbose=verbose)

    if verbose:
        print()
        total_rooms = sum(len(rooms) for rooms in result["wings"].values())
        print(f"Palace ready: {len(result['wings'])} wings, {total_rooms} rooms")
        print(f"  Path:     {result['path']}")
        print(f"  ChromaDB: {'✓' if result['chromadb'] else '✗'}")
        print(f"  KG:       {'✓' if result['kg'] else '✗'}")
        for wing, rooms in result["wings"].items():
            print(f"  {wing}: {', '.join(rooms)}")
    else:
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
