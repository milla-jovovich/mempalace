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
    mempalace context pack                Build a budgeted agent context pack
    mempalace wake-up --wing my_app       Wake-up for a specific project
    mempalace status                      Show what's been filed

Examples:
    mempalace init ~/projects/my_app
    mempalace mine ~/projects/my_app
    mempalace mine ~/chats/claude-sessions --mode convos
    mempalace search "why did we switch to GraphQL"
    mempalace context pack --project my_app --query "auth decisions"
    mempalace search "pricing discussion" --wing my_app --room costs
"""

import os
import sys
import json
import shlex
import argparse
from pathlib import Path

from .config import MempalaceConfig


def _print_json(payload):
    text = json.dumps(payload, indent=2, ensure_ascii=False)
    try:
        print(text)
    except UnicodeEncodeError:
        encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
        safe_text = text.encode(encoding, errors="backslashreplace").decode(encoding)
        print(safe_text)


def _parse_json_option(raw_value, field_name):
    if raw_value is None:
        return None
    try:
        parsed = json.loads(raw_value)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"{field_name} must be valid JSON") from exc
    if not isinstance(parsed, dict):
        raise SystemExit(f"{field_name} must be a JSON object")
    return parsed


def _project_tracker(args):
    from .project_tracker import ProjectTracker

    return ProjectTracker(db_path=MempalaceConfig().project_tracker_path)


def _context_manager(args):
    from .context_manager import ContextManager

    palace_path = os.path.expanduser(args.palace) if args.palace else MempalaceConfig().palace_path
    return ContextManager(palace_path=palace_path)


def _tracker_error(exc):
    print(f"Tracker error: {exc}", file=sys.stderr)
    raise SystemExit(1) from exc


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
    # Expand ~ and resolve to absolute path so split_mega_files sees a real path
    argv = ["--source", str(Path(args.dir).expanduser().resolve())]
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
    migrate(
        palace_path=palace_path,
        dry_run=args.dry_run,
        confirm=getattr(args, "yes", False),
    )


def cmd_status(args):
    from .miner import status

    palace_path = os.path.expanduser(args.palace) if args.palace else MempalaceConfig().palace_path
    status(palace_path=palace_path)


def cmd_project_register(args):
    from .project_tracker import ProjectTrackerError

    tracker = _project_tracker(args)
    try:
        result = tracker.register_project(
            args.path,
            name=args.name,
            wing=args.wing,
            source_type=args.source_type,
            status=args.status,
            metadata=_parse_json_option(args.metadata_json, "metadata_json"),
        )
    except ProjectTrackerError as exc:
        _tracker_error(exc)
    _print_json(result)


def cmd_project_list(args):
    tracker = _project_tracker(args)
    _print_json(tracker.list_projects(limit=args.limit))


def cmd_project_status(args):
    from .project_tracker import ProjectTrackerError

    tracker = _project_tracker(args)
    try:
        result = tracker.project_status(selector=args.project)
    except ProjectTrackerError as exc:
        _tracker_error(exc)
    _print_json(result)


def cmd_task_start(args):
    from .project_tracker import ProjectTrackerError

    tracker = _project_tracker(args)
    try:
        result = tracker.start_task(
            args.project,
            args.title,
            status=args.status,
            stage=args.stage,
            percent=args.percent,
            summary=args.summary,
            metadata=_parse_json_option(args.metadata_json, "metadata_json"),
        )
    except ProjectTrackerError as exc:
        _tracker_error(exc)
    _print_json(result)


def cmd_task_update(args):
    from .project_tracker import ProjectTrackerError

    tracker = _project_tracker(args)
    try:
        result = tracker.update_task(
            args.task_id,
            status=args.status,
            stage=args.stage,
            percent=args.percent,
            summary=args.summary,
            metadata=_parse_json_option(args.metadata_json, "metadata_json"),
        )
    except ProjectTrackerError as exc:
        _tracker_error(exc)
    _print_json(result)


def cmd_task_log(args):
    from .project_tracker import ProjectTrackerError

    tracker = _project_tracker(args)
    try:
        result = tracker.log_event(
            args.task_id,
            args.message,
            level=args.level,
            kind=args.kind,
            stage=args.stage,
            percent=args.percent,
            payload=_parse_json_option(args.payload_json, "payload_json"),
        )
    except ProjectTrackerError as exc:
        _tracker_error(exc)
    _print_json(result)


def cmd_task_checkpoint(args):
    from .project_tracker import ProjectTrackerError

    tracker = _project_tracker(args)
    try:
        result = tracker.add_checkpoint(
            args.task_id,
            args.summary,
            stage=args.stage,
            state=_parse_json_option(args.state_json, "state_json"),
        )
    except ProjectTrackerError as exc:
        _tracker_error(exc)
    _print_json(result)


def cmd_task_show(args):
    from .project_tracker import ProjectTrackerError

    tracker = _project_tracker(args)
    try:
        result = tracker.get_task(
            args.task_id,
            include_events=args.events,
            include_checkpoints=args.checkpoints,
        )
    except ProjectTrackerError as exc:
        _tracker_error(exc)
    _print_json(result)


def cmd_task_resume(args):
    from .project_tracker import ProjectTrackerError

    tracker = _project_tracker(args)
    try:
        result = tracker.resume_task(
            task_id=args.task_id,
            project_selector=args.project,
            events_limit=args.events,
            checkpoints_limit=args.checkpoints,
        )
    except ProjectTrackerError as exc:
        _tracker_error(exc)
    _print_json(result)


def cmd_context_pack(args):
    from .context_manager import ContextManagerError

    manager = _context_manager(args)
    try:
        result = manager.build_context_pack(
            query=args.query,
            wing=args.wing,
            room=args.room,
            task_id=args.task_id,
            project_selector=args.project,
            agent_name=args.agent,
            memory_results=args.memory_results,
            search_results=args.search_results,
            events_limit=args.events,
            checkpoints_limit=args.checkpoints,
            diary_entries=args.diary_entries,
            max_chars=args.max_chars,
        )
    except ContextManagerError as exc:
        print(f"Context error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    _print_json(result)


def cmd_repair(args):
    """Rebuild palace vector index from SQLite metadata."""
    import shutil
    from .backends.chroma import ChromaBackend
    from .migrate import confirm_destructive_action, contains_palace_database

    palace_path = os.path.abspath(
        os.path.expanduser(args.palace) if args.palace else MempalaceConfig().palace_path
    )
    db_path = os.path.join(palace_path, "chroma.sqlite3")

    if not os.path.isdir(palace_path):
        print(f"\n  No palace found at {palace_path}")
        return
    if not contains_palace_database(palace_path):
        print(f"\n  No palace database found at {db_path}")
        return

    print(f"\n{'=' * 55}")
    print("  MemPalace Repair")
    print(f"{'=' * 55}\n")
    print(f"  Palace: {palace_path}")

    backend = ChromaBackend()

    # Try to read existing drawers
    try:
        col = backend.get_collection(palace_path, "mempalace_drawers")
        total = col.count()
        print(f"  Drawers found: {total}")
    except Exception as e:
        print(f"  Error reading palace: {e}")
        print("  Cannot recover — palace may need to be re-mined from source files.")
        return

    if total == 0:
        print("  Nothing to repair.")
        return

    if not confirm_destructive_action(
        "Repair", palace_path, assume_yes=getattr(args, "yes", False)
    ):
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
    palace_path = os.path.normpath(palace_path)
    backup_path = palace_path + ".backup"
    if os.path.exists(backup_path):
        if not contains_palace_database(backup_path):
            print(
                "  Backup validation failed: backup path exists but does not contain chroma.sqlite3. "
                f"Please remove or rename: {backup_path}"
            )
            return
        shutil.rmtree(backup_path)
    print(f"  Backing up to {backup_path}...")
    shutil.copytree(palace_path, backup_path)

    print("  Rebuilding collection...")
    backend.delete_collection(palace_path, "mempalace_drawers")
    new_col = backend.create_collection(palace_path, "mempalace_drawers")

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


def cmd_compress(args):
    """Compress drawers in a wing using AAAK Dialect."""
    from .backends.chroma import ChromaBackend
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
    backend = ChromaBackend()
    try:
        col = backend.get_collection(palace_path, "mempalace_drawers")
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
            kwargs = {
                "include": ["documents", "metadatas"],
                "limit": _BATCH,
                "offset": offset,
            }
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
        total_compressed += stats["summary_chars"]

        compressed_entries.append((doc_id, compressed, meta, stats))

        if args.dry_run:
            wing_name = meta.get("wing", "?")
            room_name = meta.get("room", "?")
            source = Path(meta.get("source_file", "?")).name
            print(f"  [{wing_name}/{room_name}] {source}")
            print(
                f"    {stats['original_tokens_est']}t -> {stats['summary_tokens_est']}t ({stats['size_ratio']:.1f}x)"
            )
            print(f"    {compressed}")
            print()

    # Store compressed versions (unless dry-run)
    if not args.dry_run:
        try:
            comp_col = backend.get_or_create_collection(palace_path, "mempalace_compressed")
            for doc_id, compressed, meta, stats in compressed_entries:
                comp_meta = dict(meta)
                comp_meta["compression_ratio"] = round(stats["size_ratio"], 1)
                comp_meta["original_tokens"] = stats["original_tokens_est"]
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
    # Estimate tokens from char count (~3.8 chars/token for English text)
    orig_tokens = max(1, int(total_original / 3.8))
    comp_tokens = max(1, int(total_compressed / 3.8))
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
        "--yes",
        action="store_true",
        help="Auto-accept all detected entities (non-interactive)",
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

    # project tracker
    p_project = sub.add_parser("project", help="Manage tracked projects")
    project_sub = p_project.add_subparsers(dest="project_action")

    p_project_register = project_sub.add_parser("register", help="Register a local project path")
    p_project_register.add_argument("path", help="Project directory path")
    p_project_register.add_argument("--name", default=None, help="Override project display name")
    p_project_register.add_argument("--wing", default=None, help="Override linked MemPalace wing")
    p_project_register.add_argument(
        "--source-type",
        default="local",
        help="Project source type (default: local)",
    )
    p_project_register.add_argument(
        "--status",
        choices=["active", "paused", "archived"],
        default="active",
        help="Project lifecycle status",
    )
    p_project_register.add_argument(
        "--metadata-json",
        default=None,
        help="Extra project metadata as a JSON object",
    )

    p_project_list = project_sub.add_parser("list", help="List tracked projects")
    p_project_list.add_argument("--limit", type=int, default=50, help="Max projects to return")

    p_project_status = project_sub.add_parser(
        "status",
        help="Show one tracked project or all tracked projects",
    )
    p_project_status.add_argument(
        "project",
        nargs="?",
        default=None,
        help="Project id, path, or name (omit for all projects)",
    )

    p_task = sub.add_parser("task", help="Manage tracked tasks")
    task_sub = p_task.add_subparsers(dest="task_action")

    p_task_start = task_sub.add_parser("start", help="Start a tracked task for a project")
    p_task_start.add_argument("project", help="Project id, path, or name")
    p_task_start.add_argument("title", help="Task title")
    p_task_start.add_argument(
        "--status",
        choices=["queued", "running", "waiting", "completed", "failed", "cancelled"],
        default="running",
        help="Initial task status",
    )
    p_task_start.add_argument("--stage", default=None, help="Current task stage")
    p_task_start.add_argument("--percent", type=float, default=None, help="Completion percent")
    p_task_start.add_argument("--summary", default=None, help="Short task summary")
    p_task_start.add_argument(
        "--metadata-json",
        default=None,
        help="Extra task metadata as a JSON object",
    )

    p_task_update = task_sub.add_parser("update", help="Update tracked task status/progress")
    p_task_update.add_argument("task_id", help="Task id")
    p_task_update.add_argument(
        "--status",
        choices=["queued", "running", "waiting", "completed", "failed", "cancelled"],
        default=None,
        help="New task status",
    )
    p_task_update.add_argument("--stage", default=None, help="Current task stage")
    p_task_update.add_argument("--percent", type=float, default=None, help="Completion percent")
    p_task_update.add_argument("--summary", default=None, help="Updated summary")
    p_task_update.add_argument(
        "--metadata-json",
        default=None,
        help="Task metadata patch as a JSON object",
    )

    p_task_log = task_sub.add_parser("log", help="Append a structured task event")
    p_task_log.add_argument("task_id", help="Task id")
    p_task_log.add_argument("message", help="Log message")
    p_task_log.add_argument(
        "--level",
        choices=["debug", "info", "warning", "error"],
        default="info",
        help="Event level",
    )
    p_task_log.add_argument("--kind", default="log", help="Event kind")
    p_task_log.add_argument("--stage", default=None, help="Stage associated with the event")
    p_task_log.add_argument("--percent", type=float, default=None, help="Completion percent")
    p_task_log.add_argument(
        "--payload-json",
        default=None,
        help="Event payload as a JSON object",
    )

    p_task_checkpoint = task_sub.add_parser("checkpoint", help="Save a resumable checkpoint")
    p_task_checkpoint.add_argument("task_id", help="Task id")
    p_task_checkpoint.add_argument("summary", help="Checkpoint summary")
    p_task_checkpoint.add_argument("--stage", default=None, help="Checkpoint stage")
    p_task_checkpoint.add_argument(
        "--state-json",
        default=None,
        help="Checkpoint state as a JSON object",
    )

    p_task_show = task_sub.add_parser("show", help="Show a tracked task")
    p_task_show.add_argument("task_id", help="Task id")
    p_task_show.add_argument("--events", type=int, default=20, help="Recent events to include")
    p_task_show.add_argument(
        "--checkpoints",
        type=int,
        default=5,
        help="Recent checkpoints to include",
    )

    p_task_resume = task_sub.add_parser("resume", help="Recover the latest task state")
    p_task_resume.add_argument("task_id", nargs="?", default=None, help="Task id (optional)")
    p_task_resume.add_argument(
        "--project",
        default=None,
        help="Project id, path, or name (used when task_id is omitted)",
    )
    p_task_resume.add_argument("--events", type=int, default=20, help="Recent events to include")
    p_task_resume.add_argument(
        "--checkpoints",
        type=int,
        default=5,
        help="Recent checkpoints to include",
    )

    p_context = sub.add_parser(
        "context",
        help="Build a budgeted context pack from memory and tracked work",
    )
    context_sub = p_context.add_subparsers(dest="context_action")

    p_context_pack = context_sub.add_parser(
        "pack",
        help="Assemble wake-up, retrieval, resume state, and event evidence",
    )
    p_context_pack.add_argument("--query", default=None, help="Natural language query to ground search")
    p_context_pack.add_argument("--wing", default=None, help="Limit memory retrieval to one wing")
    p_context_pack.add_argument("--room", default=None, help="Limit memory retrieval to one room")
    p_context_pack.add_argument("--task-id", default=None, help="Tracked task id to resume")
    p_context_pack.add_argument(
        "--project",
        default=None,
        help="Project id, path, or name for latest-task recovery",
    )
    p_context_pack.add_argument(
        "--agent",
        default=None,
        help="Agent name whose diary entries should be included",
    )
    p_context_pack.add_argument(
        "--memory-results",
        type=int,
        default=5,
        help="Number of wing/room recall results to include",
    )
    p_context_pack.add_argument(
        "--search-results",
        type=int,
        default=5,
        help="Number of semantic search hits to include",
    )
    p_context_pack.add_argument(
        "--events",
        type=int,
        default=8,
        help="Recent task events to include",
    )
    p_context_pack.add_argument(
        "--checkpoints",
        type=int,
        default=3,
        help="Recent checkpoints to inspect",
    )
    p_context_pack.add_argument(
        "--diary-entries",
        type=int,
        default=3,
        help="Recent diary entries to include",
    )
    p_context_pack.add_argument(
        "--max-chars",
        type=int,
        default=12000,
        help="Approximate max context size in characters",
    )

    # repair
    sub.add_parser(
        "repair",
        help="Rebuild palace vector index from stored data (fixes segfaults after corruption)",
    ).add_argument("--yes", action="store_true", help="Skip confirmation for destructive changes")

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
    p_migrate.add_argument(
        "--yes", action="store_true", help="Skip confirmation for destructive changes"
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

    if args.command == "project":
        action = getattr(args, "project_action", None)
        if not action:
            p_project.print_help()
            return
        {
            "register": cmd_project_register,
            "list": cmd_project_list,
            "status": cmd_project_status,
        }[action](args)
        return

    if args.command == "task":
        action = getattr(args, "task_action", None)
        if not action:
            p_task.print_help()
            return
        {
            "start": cmd_task_start,
            "update": cmd_task_update,
            "log": cmd_task_log,
            "checkpoint": cmd_task_checkpoint,
            "show": cmd_task_show,
            "resume": cmd_task_resume,
        }[action](args)
        return

    if args.command == "context":
        action = getattr(args, "context_action", None)
        if not action:
            p_context.print_help()
            return
        {
            "pack": cmd_context_pack,
        }[action](args)
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
        "status": cmd_status,
    }
    dispatch[args.command](args)


if __name__ == "__main__":
    main()
