#!/usr/bin/env python3
"""
MemPalace — Give your AI a memory. No API key required.

Two ways to ingest:
  Projects:      mempalace mine ~/projects/my_app          (code, docs, notes)
  Conversations: mempalace mine ~/chats/ --mode convos     (Claude, ChatGPT, Slack)

Same palace. Same search. Different ingest strategies.

Commands:
    mempalace init <dir>                  Detect rooms from folder structure
    mempalace split <dir>                 Split concatenated mega-files into per-session files
    mempalace mine <dir>                  Mine project files (default)
    mempalace mine <dir> --mode convos    Mine conversation exports
    mempalace search "query"              Find anything, exact words
    mempalace mcp                         Show MCP setup command
    mempalace wake-up                     Show L0 + L1 wake-up context
    mempalace wake-up --wing my_app       Wake-up for a specific project
    mempalace status                      Show what's been filed

Examples:
    mempalace init ~/projects/my_app
    mempalace mine ~/projects/my_app
    mempalace mine ~/chats/claude-sessions --mode convos
    mempalace search "why did we switch to GraphQL"
    mempalace search "pricing discussion" --wing my_app --room costs
"""

import os
import sys
import shlex
import argparse
from pathlib import Path

from .config import MempalaceConfig


def _resolve_path(p: str) -> str:
    """Resolve a path, handling symlinks (e.g. macOS /var → /private/var)."""
    try:
        return str(Path(p).resolve())
    except OSError:
        return p


def cmd_init(args):
    import json
    from pathlib import Path
    from .entity_detector import scan_for_detection, detect_entities, confirm_entities
    from .room_detector_local import detect_rooms_local

    # Pass 1: auto-detect people and projects from file content
    print(f"\n  Scanning for entities in: {args.dir}")
    files = scan_for_detection(args.dir)
    if files:
        print(f"  Reading {len(files)} files...")
        detected = detect_entities(files)
        total = len(detected["people"]) + len(detected["projects"]) + len(detected["uncertain"])
        if total > 0:
            confirmed = confirm_entities(detected, yes=getattr(args, "yes", False))
            # Save confirmed entities to <project>/entities.json for the miner
            if confirmed["people"] or confirmed["projects"]:
                entities_path = Path(args.dir).expanduser().resolve() / "entities.json"
                with open(entities_path, "w") as f:
                    json.dump(confirmed, f, indent=2)
                print(f"  Entities saved: {entities_path}")
        else:
            print("  No entities detected — proceeding with directory-based rooms.")

    # Pass 2: detect rooms from folder structure
    detect_rooms_local(project_dir=args.dir, yes=getattr(args, "yes", False))
    MempalaceConfig().init()


def cmd_mine(args):
    palace_path = os.path.expanduser(args.palace) if args.palace else MempalaceConfig().palace_path
    include_ignored = []
    for raw in args.include_ignored or []:
        include_ignored.extend(part.strip() for part in raw.split(",") if part.strip())

    # --force: delete existing drawers for this directory before re-mining
    if getattr(args, "force", False) and not args.dry_run:
        _force_clean(palace_path, args.dir)

    if args.mode == "convos":
        from .convo_miner import mine_convos

        mine_convos(
            convo_dir=args.dir,
            palace_path=palace_path,
            wing=args.wing,
            agent=args.agent,
            limit=args.limit,
            dry_run=args.dry_run,
            extract_mode=args.extract,
        )
    else:
        from .miner import mine

        mine(
            project_dir=args.dir,
            palace_path=palace_path,
            wing_override=args.wing,
            agent=args.agent,
            limit=args.limit,
            dry_run=args.dry_run,
            respect_gitignore=not args.no_gitignore,
            include_ignored=include_ignored,
        )


def _force_clean(palace_path: str, source_dir: str):
    """Delete all drawers from files under source_dir — used by --force re-mine."""
    import chromadb
    from pathlib import Path

    try:
        client = chromadb.PersistentClient(path=palace_path)
        col = client.get_collection("mempalace_drawers")
    except Exception:
        return  # No palace yet — nothing to clean

    source_prefix = str(Path(source_dir).expanduser().resolve())
    batch_size = 500
    offset = 0
    to_delete = []

    while True:
        batch = col.get(limit=batch_size, offset=offset, include=["metadatas"])
        if not batch["ids"]:
            break
        for drawer_id, meta in zip(batch["ids"], batch["metadatas"]):
            sf = meta.get("source_file", "")
            # Resolve symlinks for consistent comparison (macOS /var → /private/var)
            try:
                sf_resolved = str(Path(sf).resolve()) if sf else ""
            except OSError:
                sf_resolved = sf
            if sf_resolved.startswith(source_prefix):
                to_delete.append(drawer_id)
        offset += len(batch["ids"])

    if to_delete:
        print(f"\n  --force: deleting {len(to_delete)} existing drawers from {source_prefix}...")
        for i in range(0, len(to_delete), 100):
            col.delete(ids=to_delete[i:i + 100])
        print(f"  Deleted. Re-mining fresh.\n")


def cmd_search(args):
    from .searcher import search, SearchError

    palace_path = os.path.expanduser(args.palace) if args.palace else MempalaceConfig().palace_path
    try:
        search(
            query=args.query,
            palace_path=palace_path,
            wing=args.wing,
            room=args.room,
            n_results=args.results,
        )
    except SearchError:
        sys.exit(1)


def cmd_wakeup(args):
    """Show L0 (identity) + L1 (essential story) — the wake-up context."""
    from .layers import MemoryStack

    palace_path = os.path.expanduser(args.palace) if args.palace else MempalaceConfig().palace_path
    stack = MemoryStack(palace_path=palace_path)

    text = stack.wake_up(wing=args.wing)
    tokens = len(text) // 4
    print(f"Wake-up text (~{tokens} tokens):")
    print("=" * 50)
    print(text)


def cmd_split(args):
    """Split concatenated transcript mega-files into per-session files."""
    from .split_mega_files import main as split_main
    import sys

    # Rebuild argv for split_mega_files argparse
    argv = ["--source", args.dir]
    if args.output_dir:
        argv += ["--output-dir", args.output_dir]
    if args.dry_run:
        argv.append("--dry-run")
    if args.min_sessions != 2:
        argv += ["--min-sessions", str(args.min_sessions)]

    old_argv = sys.argv
    sys.argv = ["mempalace split"] + argv
    try:
        split_main()
    finally:
        sys.argv = old_argv


def cmd_status(args):
    from .miner import status

    palace_path = os.path.expanduser(args.palace) if args.palace else MempalaceConfig().palace_path
    status(palace_path=palace_path)


def cmd_repair(args):
    """Rebuild palace vector index from SQLite metadata."""
    import chromadb
    import shutil

    palace_path = os.path.expanduser(args.palace) if args.palace else MempalaceConfig().palace_path

    if not os.path.isdir(palace_path):
        print(f"\n  No palace found at {palace_path}")
        return

    print(f"\n{'=' * 55}")
    print("  MemPalace Repair")
    print(f"{'=' * 55}\n")
    print(f"  Palace: {palace_path}")

    # Try to read existing drawers
    try:
        client = chromadb.PersistentClient(path=palace_path)
        col = client.get_collection("mempalace_drawers")
        total = col.count()
        print(f"  Drawers found: {total}")
    except Exception as e:
        print(f"  Error reading palace: {e}")
        print("  Cannot recover — palace may need to be re-mined from source files.")
        return

    if total == 0:
        print("  Nothing to repair.")
        return

    # Extract all drawers in batches
    print("\n  Extracting drawers...")
    batch_size = 5000
    all_ids = []
    all_docs = []
    all_metas = []
    offset = 0
    while offset < total:
        batch = col.get(limit=batch_size, offset=offset, include=["documents", "metadatas"])
        all_ids.extend(batch["ids"])
        all_docs.extend(batch["documents"])
        all_metas.extend(batch["metadatas"])
        offset += batch_size
    print(f"  Extracted {len(all_ids)} drawers")

    # Backup and rebuild
    palace_path = palace_path.rstrip(os.sep)
    backup_path = palace_path + ".backup"
    if os.path.exists(backup_path):
        shutil.rmtree(backup_path)
    print(f"  Backing up to {backup_path}...")
    shutil.copytree(palace_path, backup_path)

    print("  Rebuilding collection...")
    client.delete_collection("mempalace_drawers")
    new_col = client.create_collection("mempalace_drawers")

    filed = 0
    for i in range(0, len(all_ids), batch_size):
        batch_ids = all_ids[i : i + batch_size]
        batch_docs = all_docs[i : i + batch_size]
        batch_metas = all_metas[i : i + batch_size]
        new_col.add(documents=batch_docs, ids=batch_ids, metadatas=batch_metas)
        filed += len(batch_ids)
        print(f"  Re-filed {filed}/{len(all_ids)} drawers...")

    print(f"\n  Repair complete. {filed} drawers rebuilt.")
    print(f"  Backup saved at {backup_path}")
    print(f"\n{'=' * 55}\n")


def cmd_hook(args):
    """Run hook logic: reads JSON from stdin, outputs JSON to stdout."""
    from .hooks_cli import run_hook

    run_hook(hook_name=args.hook, harness=args.harness)


def cmd_instructions(args):
    """Output skill instructions to stdout."""
    from .instructions_cli import run_instructions

    run_instructions(name=args.name)


def cmd_mcp(args):
    """Show how to wire MemPalace into MCP-capable hosts."""
    base_server_cmd = "python -m mempalace.mcp_server"

    if args.palace:
        resolved_palace = str(Path(args.palace).expanduser())
        server_cmd = f"{base_server_cmd} --palace {shlex.quote(resolved_palace)}"
    else:
        server_cmd = base_server_cmd

    print("MemPalace MCP quick setup:")
    print(f"  claude mcp add mempalace -- {server_cmd}")
    print("\nRun the server directly:")
    print(f"  {server_cmd}")

    if not args.palace:
        print("\nOptional custom palace:")
        print(f"  claude mcp add mempalace -- {base_server_cmd} --palace /path/to/palace")
        print(f"  {base_server_cmd} --palace /path/to/palace")

def cmd_sync(args):
    """Sync palace with source files — re-mine changed files, report stale drawers."""
    import chromadb
    import hashlib
    from pathlib import Path

    palace_path = os.path.expanduser(args.palace) if args.palace else MempalaceConfig().palace_path

    print(f"\n{'=' * 55}")
    print("  MemPalace Sync")
    print(f"{'=' * 55}\n")

    try:
        client = chromadb.PersistentClient(path=palace_path)
        col = client.get_collection("mempalace_drawers")
    except Exception:
        print(f"  No palace found at {palace_path}")
        print("  Run: mempalace init <dir> then mempalace mine <dir>")
        sys.exit(1)

    total = col.count()
    if total == 0:
        print("  Palace is empty. Nothing to sync.")
        return

    # Collect all unique source files and their content hashes from the palace
    print(f"  Scanning {total} drawers for source files...")
    source_files = {}  # source_file -> {hash, drawer_ids, wing}
    batch_size = 500
    offset = 0
    while offset < total:
        batch = col.get(
            limit=batch_size, offset=offset, include=["metadatas"]
        )
        if not batch["ids"]:
            break
        for drawer_id, meta in zip(batch["ids"], batch["metadatas"]):
            sf = meta.get("source_file", "")
            if not sf:
                continue
            if sf not in source_files:
                source_files[sf] = {
                    "hash": meta.get("content_hash", ""),
                    "drawer_ids": [],
                    "wing": meta.get("wing", ""),
                }
            source_files[sf]["drawer_ids"].append(drawer_id)
        offset += len(batch["ids"])

    print(f"  Found {len(source_files)} unique source files\n")

    # Filter by directory if specified
    if args.dir:
        sync_dir = str(Path(args.dir).expanduser().resolve())
        source_files = {
            sf: info for sf, info in source_files.items()
            if _resolve_path(sf).startswith(sync_dir)
        }
        print(f"  Filtered to {len(source_files)} files in {sync_dir}\n")

    if not source_files:
        print("  No source files to check.")
        return

    # Check each source file for changes
    stale = []       # files that changed
    missing = []     # files that no longer exist
    fresh = 0        # files unchanged
    no_hash = 0      # files without content_hash (mined before sync feature)

    for sf, info in sorted(source_files.items()):
        if not os.path.exists(sf):
            missing.append(sf)
            continue

        stored_hash = info["hash"]
        if not stored_hash:
            no_hash += 1
            continue

        try:
            content = Path(sf).read_text(encoding="utf-8", errors="replace").strip()
            current_hash = hashlib.md5(content.encode(), usedforsecurity=False).hexdigest()
        except OSError:
            missing.append(sf)
            continue

        if current_hash != stored_hash:
            stale.append(sf)
        else:
            fresh += 1

    # Report
    print(f"  Fresh (unchanged):     {fresh}")
    print(f"  Stale (changed):       {len(stale)}")
    print(f"  Missing (deleted):     {len(missing)}")
    if no_hash:
        print(f"  No hash (legacy):      {no_hash} (re-mine with --force to add hashes)")
    print()

    if stale:
        print("  Changed files:")
        for sf in stale[:20]:
            n = len(source_files[sf]["drawer_ids"])
            print(f"    {Path(sf).name} ({n} drawers)")
        if len(stale) > 20:
            print(f"    ... and {len(stale) - 20} more")
        print()

    if missing:
        print("  Missing files:")
        for sf in missing[:10]:
            n = len(source_files[sf]["drawer_ids"])
            print(f"    {Path(sf).name} ({n} drawers)")
        if len(missing) > 10:
            print(f"    ... and {len(missing) - 10} more")
        print()

    if not stale and not missing:
        print("  Everything is up to date!")
        print(f"\n{'=' * 55}\n")
        return

    # Dry run — stop here
    if args.dry_run:
        total_stale = sum(len(source_files[sf]["drawer_ids"]) for sf in stale)
        total_missing = sum(len(source_files[sf]["drawer_ids"]) for sf in missing)
        print(f"  [DRY RUN] Would delete {total_stale} stale + {total_missing} orphaned drawers")
        print(f"  [DRY RUN] Would re-mine {len(stale)} changed files")
        print(f"\n{'=' * 55}\n")
        return

    # Delete stale drawers and re-mine
    deleted = 0
    re_mined = 0

    # Delete drawers for changed files
    if stale:
        print("  Deleting stale drawers...")
        for sf in stale:
            ids = source_files[sf]["drawer_ids"]
            # ChromaDB delete in batches
            for i in range(0, len(ids), 100):
                col.delete(ids=ids[i:i + 100])
            deleted += len(ids)
        print(f"  Deleted {deleted} stale drawers")

    # Delete drawers for missing files (if --clean flag)
    if missing and args.clean:
        print("  Cleaning orphaned drawers...")
        orphan_count = 0
        for sf in missing:
            ids = source_files[sf]["drawer_ids"]
            for i in range(0, len(ids), 100):
                col.delete(ids=ids[i:i + 100])
            orphan_count += len(ids)
        deleted += orphan_count
        print(f"  Cleaned {orphan_count} orphaned drawers")
    elif missing:
        print(f"  Skipped {len(missing)} missing files (use --clean to remove orphaned drawers)")

    # Re-mine changed files
    if stale:
        print(f"\n  Re-mining {len(stale)} changed files...")

        # Detect mode from existing metadata
        for sf in stale:
            info = source_files[sf]
            wing = info["wing"]

            # Check if this was a convo or project mine
            sample = col.get(
                where={"source_file": sf}, limit=1, include=["metadatas"]
            )
            is_convo = False
            if sample["metadatas"]:
                is_convo = sample["metadatas"][0].get("ingest_mode") == "convos"

            if is_convo:
                from .convo_miner import mine_convos
                mine_convos(
                    convo_dir=str(Path(sf).parent),
                    palace_path=palace_path,
                    wing=wing,
                    agent=args.agent,
                )
            else:
                from .miner import mine
                mine(
                    project_dir=str(Path(sf).parent),
                    palace_path=palace_path,
                    wing_override=wing,
                    agent=args.agent,
                )
            re_mined += 1

    print(f"\n  Sync complete.")
    print(f"  Deleted: {deleted} stale drawers")
    print(f"  Re-mined: {re_mined} source directories")
    print(f"\n{'=' * 55}\n")


def cmd_compress(args):
    """Compress drawers in a wing using AAAK Dialect."""
    import chromadb
    from .dialect import Dialect

    palace_path = os.path.expanduser(args.palace) if args.palace else MempalaceConfig().palace_path

    # Load dialect (with optional entity config)
    config_path = args.config
    if not config_path:
        for candidate in ["entities.json", os.path.join(palace_path, "entities.json")]:
            if os.path.exists(candidate):
                config_path = candidate
                break

    if config_path and os.path.exists(config_path):
        dialect = Dialect.from_config(config_path)
        print(f"  Loaded entity config: {config_path}")
    else:
        dialect = Dialect()

    # Connect to palace
    try:
        client = chromadb.PersistentClient(path=palace_path)
        col = client.get_collection("mempalace_drawers")
    except Exception:
        print(f"\n  No palace found at {palace_path}")
        print("  Run: mempalace init <dir> then mempalace mine <dir>")
        sys.exit(1)

    # Query drawers in batches to avoid SQLite variable limit (~999)
    where = {"wing": args.wing} if args.wing else None
    _BATCH = 500
    docs, metas, ids = [], [], []
    offset = 0
    while True:
        try:
            kwargs = {"include": ["documents", "metadatas"], "limit": _BATCH, "offset": offset}
            if where:
                kwargs["where"] = where
            batch = col.get(**kwargs)
        except Exception as e:
            if not docs:
                print(f"\n  Error reading drawers: {e}")
                sys.exit(1)
            break
        batch_docs = batch.get("documents", [])
        if not batch_docs:
            break
        docs.extend(batch_docs)
        metas.extend(batch.get("metadatas", []))
        ids.extend(batch.get("ids", []))
        offset += len(batch_docs)
        if len(batch_docs) < _BATCH:
            break

    if not docs:
        wing_label = f" in wing '{args.wing}'" if args.wing else ""
        print(f"\n  No drawers found{wing_label}.")
        return

    print(
        f"\n  Compressing {len(docs)} drawers"
        + (f" in wing '{args.wing}'" if args.wing else "")
        + "..."
    )
    print()

    total_original = 0
    total_compressed = 0
    compressed_entries = []

    for doc, meta, doc_id in zip(docs, metas, ids):
        compressed = dialect.compress(doc, metadata=meta)
        stats = dialect.compression_stats(doc, compressed)

        total_original += stats["original_chars"]
        total_compressed += stats["compressed_chars"]

        compressed_entries.append((doc_id, compressed, meta, stats))

        if args.dry_run:
            wing_name = meta.get("wing", "?")
            room_name = meta.get("room", "?")
            source = Path(meta.get("source_file", "?")).name
            print(f"  [{wing_name}/{room_name}] {source}")
            print(
                f"    {stats['original_tokens']}t -> {stats['compressed_tokens']}t ({stats['ratio']:.1f}x)"
            )
            print(f"    {compressed}")
            print()

    # Store compressed versions (unless dry-run)
    if not args.dry_run:
        try:
            comp_col = client.get_or_create_collection("mempalace_compressed")
            for doc_id, compressed, meta, stats in compressed_entries:
                comp_meta = dict(meta)
                comp_meta["compression_ratio"] = round(stats["ratio"], 1)
                comp_meta["original_tokens"] = stats["original_tokens"]
                comp_col.upsert(
                    ids=[doc_id],
                    documents=[compressed],
                    metadatas=[comp_meta],
                )
            print(
                f"  Stored {len(compressed_entries)} compressed drawers in 'mempalace_compressed' collection."
            )
        except Exception as e:
            print(f"  Error storing compressed drawers: {e}")
            sys.exit(1)

    # Summary
    ratio = total_original / max(total_compressed, 1)
    orig_tokens = Dialect.count_tokens("x" * total_original)
    comp_tokens = Dialect.count_tokens("x" * total_compressed)
    print(f"  Total: {orig_tokens:,}t -> {comp_tokens:,}t ({ratio:.1f}x compression)")
    if args.dry_run:
        print("  (dry run -- nothing stored)")


def main():
    parser = argparse.ArgumentParser(
        description="MemPalace — Give your AI a memory. No API key required.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--palace",
        default=None,
        help="Where the palace lives (default: from ~/.mempalace/config.json or ~/.mempalace/palace)",
    )

    sub = parser.add_subparsers(dest="command")

    # init
    p_init = sub.add_parser("init", help="Detect rooms from your folder structure")
    p_init.add_argument("dir", help="Project directory to set up")
    p_init.add_argument(
        "--yes", action="store_true", help="Auto-accept all detected entities (non-interactive)"
    )

    # mine
    p_mine = sub.add_parser("mine", help="Mine files into the palace")
    p_mine.add_argument("dir", help="Directory to mine")
    p_mine.add_argument(
        "--mode",
        choices=["projects", "convos"],
        default="projects",
        help="Ingest mode: 'projects' for code/docs (default), 'convos' for chat exports",
    )
    p_mine.add_argument("--wing", default=None, help="Wing name (default: directory name)")
    p_mine.add_argument(
        "--no-gitignore",
        action="store_true",
        help="Don't respect .gitignore files when scanning project files",
    )
    p_mine.add_argument(
        "--include-ignored",
        action="append",
        default=[],
        help="Always scan these project-relative paths even if ignored; repeat or pass comma-separated paths",
    )
    p_mine.add_argument(
        "--agent",
        default="mempalace",
        help="Your name — recorded on every drawer (default: mempalace)",
    )
    p_mine.add_argument("--limit", type=int, default=0, help="Max files to process (0 = all)")
    p_mine.add_argument(
        "--dry-run", action="store_true", help="Show what would be filed without filing"
    )
    p_mine.add_argument(
        "--force",
        action="store_true",
        help="Re-mine files even if already filed (deletes old drawers first)",
    )
    p_mine.add_argument(
        "--extract",
        choices=["exchange", "general"],
        default="exchange",
        help="Extraction strategy for convos mode: 'exchange' (default) or 'general' (5 memory types)",
    )

    # search
    p_search = sub.add_parser("search", help="Find anything, exact words")
    p_search.add_argument("query", help="What to search for")
    p_search.add_argument("--wing", default=None, help="Limit to one project")
    p_search.add_argument("--room", default=None, help="Limit to one room")
    p_search.add_argument("--results", type=int, default=5, help="Number of results")

    # compress
    p_compress = sub.add_parser(
        "compress", help="Compress drawers using AAAK Dialect (~30x reduction)"
    )
    p_compress.add_argument("--wing", default=None, help="Wing to compress (default: all wings)")
    p_compress.add_argument(
        "--dry-run", action="store_true", help="Preview compression without storing"
    )
    p_compress.add_argument(
        "--config", default=None, help="Entity config JSON (e.g. entities.json)"
    )

    # wake-up
    p_wakeup = sub.add_parser("wake-up", help="Show L0 + L1 wake-up context (~600-900 tokens)")
    p_wakeup.add_argument("--wing", default=None, help="Wake-up for a specific project/wing")

    # split
    p_split = sub.add_parser(
        "split",
        help="Split concatenated transcript mega-files into per-session files (run before mine)",
    )
    p_split.add_argument("dir", help="Directory containing transcript files")
    p_split.add_argument(
        "--output-dir",
        default=None,
        help="Write split files here (default: same directory as source files)",
    )
    p_split.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be split without writing files",
    )
    p_split.add_argument(
        "--min-sessions",
        type=int,
        default=2,
        help="Only split files containing at least N sessions (default: 2)",
    )

    # hook
    p_hook = sub.add_parser(
        "hook",
        help="Run hook logic (reads JSON from stdin, outputs JSON to stdout)",
    )
    hook_sub = p_hook.add_subparsers(dest="hook_action")
    p_hook_run = hook_sub.add_parser("run", help="Execute a hook")
    p_hook_run.add_argument(
        "--hook",
        required=True,
        choices=["session-start", "stop", "precompact"],
        help="Hook name to run",
    )
    p_hook_run.add_argument(
        "--harness",
        required=True,
        choices=["claude-code", "codex"],
        help="Harness type (determines stdin JSON format)",
    )

    # instructions
    p_instructions = sub.add_parser(
        "instructions",
        help="Output skill instructions to stdout",
    )
    instructions_sub = p_instructions.add_subparsers(dest="instructions_name")
    for instr_name in ["init", "search", "mine", "help", "status"]:
        instructions_sub.add_parser(instr_name, help=f"Output {instr_name} instructions")

    # sync
    p_sync = sub.add_parser(
        "sync",
        help="Detect changed source files and re-mine stale drawers",
    )
    p_sync.add_argument(
        "--dir",
        default=None,
        help="Only sync files under this directory (default: all source files)",
    )
    p_sync.add_argument(
        "--clean",
        action="store_true",
        help="Also delete drawers for source files that no longer exist",
    )
    p_sync.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would change without modifying the palace",
    )
    p_sync.add_argument(
        "--agent",
        default="mempalace",
        help="Your name — recorded on re-mined drawers (default: mempalace)",
    )
    # repair
    sub.add_parser(
        "repair",
        help="Rebuild palace vector index from stored data (fixes segfaults after corruption)",
    )

    # mcp
    sub.add_parser(
        "mcp",
        help="Show MCP setup command for connecting MemPalace to your AI client",
    )

    # status
    sub.add_parser("status", help="Show what's been filed")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    # Handle two-level subcommands
    if args.command == "hook":
        if not getattr(args, "hook_action", None):
            p_hook.print_help()
            return
        cmd_hook(args)
        return

    if args.command == "instructions":
        name = getattr(args, "instructions_name", None)
        if not name:
            p_instructions.print_help()
            return
        args.name = name
        cmd_instructions(args)
        return

    dispatch = {
        "init": cmd_init,
        "mine": cmd_mine,
        "sync": cmd_sync,
        "split": cmd_split,
        "search": cmd_search,
        "mcp": cmd_mcp,
        "compress": cmd_compress,
        "wake-up": cmd_wakeup,
        "repair": cmd_repair,
        "status": cmd_status,
    }
    dispatch[args.command](args)


if __name__ == "__main__":
    main()
