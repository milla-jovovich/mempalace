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
from .palace import get_collection


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


def cmd_migrate(args):
    """Migrate palace from a different ChromaDB version."""
    from .migrate import migrate

    palace_path = os.path.expanduser(args.palace) if args.palace else MempalaceConfig().palace_path
    migrate(palace_path=palace_path, dry_run=args.dry_run)


def cmd_status(args):
    from .miner import status

    palace_path = os.path.expanduser(args.palace) if args.palace else MempalaceConfig().palace_path
    status(palace_path=palace_path)


def cmd_repair(args):
    """Rebuild palace vector index from stored data."""
    import shutil
    from .db import detect_backend

    palace_path = os.path.expanduser(args.palace) if args.palace else MempalaceConfig().palace_path

    if not os.path.isdir(palace_path):
        print(f"\n  No palace found at {palace_path}")
        return

    print(f"\n{'=' * 55}")
    print("  MemPalace Repair")
    print(f"{'=' * 55}\n")
    print(f"  Palace: {palace_path}")
    print(f"  Backend: {detect_backend(palace_path)}")

    # Try to read existing drawers
    try:
        col = get_collection(palace_path)
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

    print("  Rebuilding — re-mining into fresh palace...")
    shutil.rmtree(palace_path)
    new_col = get_collection(palace_path)

    filed = 0
    for i in range(0, len(all_ids), batch_size):
        batch_ids = all_ids[i : i + batch_size]
        batch_docs = all_docs[i : i + batch_size]
        batch_metas = all_metas[i : i + batch_size]
        new_col.upsert(documents=batch_docs, ids=batch_ids, metadatas=batch_metas)
        filed += len(batch_ids)
        print(f"  Re-filed {filed}/{len(all_ids)} drawers...")

    print(f"\n  Repair complete. {filed} drawers rebuilt.")
    print(f"  Backup saved at {backup_path}")
    print(f"\n{'=' * 55}\n")


def cmd_reindex(args):
    """Re-embed all drawers with the current (or specified) embedder."""
    from .embeddings import get_embedder, resolve_model_name

    palace_path = os.path.expanduser(args.palace) if args.palace else MempalaceConfig().palace_path
    config = MempalaceConfig()

    if not os.path.isdir(palace_path):
        print(f"\n  No palace found at {palace_path}")
        return

    # Determine target embedder
    if args.embedder:
        embedder_config = {
            "embedder": args.embedder,
            "embedder_options": {"device": args.device or "cpu"},
        }
        if args.embedder == "ollama":
            opts = embedder_config["embedder_options"]
            opts["model"] = args.ollama_model or "nomic-embed-text"
            if args.ollama_url:
                opts["base_url"] = args.ollama_url
    else:
        embedder_config = config.embedder_config

    resolved_name = resolve_model_name(embedder_config.get("embedder", "all-MiniLM-L6-v2"))
    if embedder_config.get("embedder") == "ollama":
        display_name = (
            f"ollama/{embedder_config['embedder_options'].get('model', 'nomic-embed-text')}"
        )
    else:
        display_name = resolved_name

    print(f"\n{'=' * 55}")
    print("  MemPalace Reindex")
    print(f"{'=' * 55}\n")
    print(f"  Palace:   {palace_path}")
    print(f"  Embedder: {display_name}")

    embedder = get_embedder(embedder_config)
    print(f"  Dimension: {embedder.dimension}")

    # Read all existing records
    from .db import open_collection

    col = open_collection(palace_path, embedder=embedder)
    total = col.count()

    if total == 0:
        print("  Nothing to reindex.")
        return

    print(f"  Drawers:  {total}")

    if args.dry_run:
        print("\n  DRY RUN — nothing will be changed.")
        # Show current model distribution
        batch = col.get(limit=min(total, 100), include=["metadatas"])
        models = {}
        for m in batch.get("metadatas", []):
            em = m.get("embedding_model", "unknown")
            models[em] = models.get(em, 0) + 1
        print("\n  Current embedding models (sample):")
        for model, count in sorted(models.items(), key=lambda x: -x[1]):
            print(f"    {model}: {count} drawers")
        print(f"\n{'=' * 55}\n")
        return

    print(f"\n  Re-embedding {total} drawers...")

    batch_size = 100
    offset = 0
    processed = 0

    while offset < total:
        batch = col.get(limit=batch_size, offset=offset, include=["documents", "metadatas"])
        batch_ids = batch["ids"]
        batch_docs = batch["documents"]
        batch_metas = batch["metadatas"]

        if not batch_ids:
            break

        # Re-embed
        new_embeddings = embedder.embed(batch_docs)

        # Update metadata with new model name
        updated_metas = []
        for m in batch_metas:
            m2 = dict(m)
            m2["embedding_model"] = embedder.model_name
            updated_metas.append(m2)

        # Write back with new embeddings
        col.upsert(
            documents=batch_docs,
            ids=batch_ids,
            metadatas=updated_metas,
            embeddings=new_embeddings,
        )

        processed += len(batch_ids)
        print(f"  Re-embedded {processed}/{total} drawers...")
        offset += len(batch_ids)

    print(f"\n{'=' * 55}")
    print(f"  Reindex complete. {processed} drawers re-embedded with {display_name}.")
    print(f"{'=' * 55}\n")


def cmd_embedders(args):
    """List available embedding models."""
    from .embeddings import list_embedders

    config = MempalaceConfig()
    current = config.embedder_config.get("embedder", "all-MiniLM-L6-v2")

    print(f"\n{'=' * 70}")
    print("  Available Embedding Models")
    print(f"{'=' * 70}\n")

    for e in list_embedders():
        marker = " ◄ active" if e["name"] == current or e["alias"] == current else ""
        dim_str = str(e["dim"]).rjust(4)
        print(f"  {e['alias']:12s}  {dim_str}d  {e['name']}")
        print(f"               {e['notes']}{marker}")
        print()

    print("  Configure in ~/.mempalace/config.json:")
    print('    {"embedder": "bge-small", "embedder_options": {"device": "cpu"}}')
    print()
    print("  For Ollama (GPU server):")
    print(
        '    {"embedder": "ollama", "embedder_options": {"model": "nomic-embed-text", "base_url": "http://server:11434"}}'
    )
    print("\n  After changing embedder, run: mempalace reindex")
    print(f"{'=' * 70}\n")


def cmd_migrate(args):
    """Migrate palace from ChromaDB to LanceDB."""
    import shutil

    palace_path = os.path.expanduser(args.palace) if args.palace else MempalaceConfig().palace_path

    if not os.path.isdir(palace_path):
        print(f"\n  No palace found at {palace_path}")
        return

    from .db import detect_backend

    current = detect_backend(palace_path)

    if current == "lance":
        print(f"\n  Palace at {palace_path} is already using LanceDB.")
        return

    print(f"\n{'=' * 55}")
    print("  MemPalace Migrate: ChromaDB → LanceDB")
    print(f"{'=' * 55}\n")
    print(f"  Palace: {palace_path}")

    # Read all data from ChromaDB
    try:
        import chromadb

        client = chromadb.PersistentClient(path=palace_path)
        col = client.get_collection("mempalace_drawers")
        total = col.count()
        print(f"  Drawers found: {total}")
    except Exception as e:
        print(f"  Error reading ChromaDB palace: {e}")
        return

    if total == 0:
        print("  Nothing to migrate.")
        return

    # Extract all data including embeddings
    print("\n  Extracting drawers from ChromaDB...")
    batch_size = 5000
    all_ids, all_docs, all_metas, all_embeddings = [], [], [], []
    offset = 0
    while offset < total:
        batch = col.get(
            limit=batch_size, offset=offset, include=["documents", "metadatas", "embeddings"]
        )
        all_ids.extend(batch["ids"])
        all_docs.extend(batch["documents"])
        all_metas.extend(batch["metadatas"])
        all_embeddings.extend(batch.get("embeddings", []))
        offset += batch_size
    print(f"  Extracted {len(all_ids)} drawers")

    has_embeddings = all_embeddings and all_embeddings[0] is not None

    # Backup ChromaDB data
    palace_path_clean = palace_path.rstrip(os.sep)
    backup_path = palace_path_clean + ".chroma-backup"
    if os.path.exists(backup_path):
        shutil.rmtree(backup_path)
    print(f"  Backing up ChromaDB to {backup_path}...")
    shutil.copytree(palace_path, backup_path)

    # Remove ChromaDB files, create fresh LanceDB palace
    shutil.rmtree(palace_path)

    from .db import open_collection

    if has_embeddings:
        print("  Transferring with original embeddings (no re-embedding needed)...")
    else:
        print("  Re-embedding all drawers (ChromaDB embeddings not available)...")

    lance_col = open_collection(palace_path, backend="lance")

    filed = 0
    for i in range(0, len(all_ids), batch_size):
        batch_ids = all_ids[i : i + batch_size]
        batch_docs = all_docs[i : i + batch_size]
        batch_metas = all_metas[i : i + batch_size]
        batch_embs = all_embeddings[i : i + batch_size] if has_embeddings else None
        lance_col.upsert(
            documents=batch_docs, ids=batch_ids, metadatas=batch_metas, embeddings=batch_embs
        )
        filed += len(batch_ids)
        print(f"  Migrated {filed}/{len(all_ids)} drawers...")

    # Also migrate compressed collection if it exists
    try:
        client2 = chromadb.PersistentClient(path=backup_path)
        comp_col = client2.get_collection("mempalace_compressed")
        comp_total = comp_col.count()
        if comp_total > 0:
            print(f"\n  Migrating {comp_total} compressed drawers...")
            comp_data = comp_col.get(
                limit=comp_total, include=["documents", "metadatas", "embeddings"]
            )
            comp_lance = open_collection(palace_path, "mempalace_compressed", backend="lance")
            comp_embs = (
                comp_data.get("embeddings")
                if comp_data.get("embeddings") and comp_data["embeddings"][0] is not None
                else None
            )
            comp_lance.upsert(
                documents=comp_data["documents"],
                ids=comp_data["ids"],
                metadatas=comp_data["metadatas"],
                embeddings=comp_embs,
            )
            print(f"  Migrated {comp_total} compressed drawers.")
    except Exception:
        pass

    print(f"\n{'=' * 55}")
    print(f"  Migration complete. {filed} drawers moved to LanceDB.")
    print(f"  ChromaDB backup at: {backup_path}")
    print("  To verify: mempalace status")
    print(f"{'=' * 55}\n")


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


def cmd_compress(args):
    """Compress drawers in a wing using AAAK Dialect."""
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
        col = get_collection(palace_path)
        if col.count() == 0:
            raise Exception("Empty palace")
    except Exception:
        print(f"\n  No palace found at {palace_path}")
        print("  Run: mempalace init <dir> then mempalace mine <dir>")
        sys.exit(1)

    # Query drawers in batches
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
            comp_col = get_collection(palace_path, "mempalace_compressed")
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

    # repair
    sub.add_parser(
        "repair",
        help="Rebuild palace vector index from stored data (fixes segfaults after corruption)",
    )

    # migrate
    sub.add_parser(
        "migrate",
        help="Migrate palace from ChromaDB to LanceDB",
    )

    # reindex
    p_reindex = sub.add_parser(
        "reindex",
        help="Re-embed all drawers with a different embedding model",
    )
    p_reindex.add_argument(
        "--embedder",
        default=None,
        help="Embedder name or alias (e.g. bge-small, ollama). Default: from config.",
    )
    p_reindex.add_argument(
        "--device",
        default=None,
        help="Device for sentence-transformers (cpu, cuda, mps)",
    )
    p_reindex.add_argument(
        "--ollama-model",
        default=None,
        help="Ollama model name (when --embedder=ollama)",
    )
    p_reindex.add_argument(
        "--ollama-url",
        default=None,
        help="Ollama server URL (when --embedder=ollama)",
    )
    p_reindex.add_argument(
        "--dry-run",
        action="store_true",
        help="Show current embedding model distribution without changing anything",
    )

    # embedders
    sub.add_parser(
        "embedders",
        help="List available embedding models",
    )

    # mcp
    sub.add_parser(
        "mcp",
        help="Show MCP setup command for connecting MemPalace to your AI client",
    )

    # status
    # migrate
    p_migrate = sub.add_parser(
        "migrate",
        help="Migrate palace from a different ChromaDB version (fixes 3.0.0 → 3.1.0 upgrade)",
    )
    p_migrate.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be migrated without changing anything",
    )

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
        "split": cmd_split,
        "search": cmd_search,
        "mcp": cmd_mcp,
        "compress": cmd_compress,
        "wake-up": cmd_wakeup,
        "repair": cmd_repair,
        "migrate": cmd_migrate,
        "reindex": cmd_reindex,
        "embedders": cmd_embedders,
        "status": cmd_status,
    }
    dispatch[args.command](args)


if __name__ == "__main__":
    main()
