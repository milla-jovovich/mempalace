# MemPalace Sync

When the user invokes this skill, follow these steps:

## 1. Run a dry-run sync first

Always start with a dry-run to preview what changed:

    mempalace sync [--dir <dir>] --dry-run [--palace <path>]

This scans all stored drawers, checks source files for changes, and reports:
- **Fresh**: files unchanged since last mine
- **Stale**: files that changed (content hash mismatch)
- **Missing**: files that no longer exist on disk
- **No hash (legacy)**: files mined before sync feature (need --force to add hashes)

## 2. Review the report with the user

Show the dry-run output and explain:
- Stale files will be re-mined (old drawers deleted, fresh content re-indexed)
- Missing files have orphaned drawers that will be cleaned up
- Legacy files need a `--force` re-mine to get content hashes

## 3. Run the actual sync

If the user confirms, run without --dry-run:

    mempalace sync [--dir <dir>] [--palace <path>]

This performs atomic per-file operations:
1. Deletes stale drawers for each changed file
2. Re-mines the file immediately (project or convo mode based on original ingest_mode)
3. Deletes orphaned drawers for missing files

### Force re-mine everything

To re-mine all tracked files regardless of hash (useful for schema upgrades):

    mempalace sync --force [--dir <dir>]

### Scope to a specific directory

    mempalace sync --dir ~/projects/myapp

Only syncs files under the given directory.

## 4. Show results and suggest next steps

After sync completes, summarize:
- Files re-mined
- Orphaned drawers cleaned
- Any errors encountered

Suggest:
- /mempalace:search — verify re-mined content is searchable
- /mempalace:status — check palace state after sync
