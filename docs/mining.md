# Mining

MemPalace ingests data through two modes: **project mining** (code, docs, notes) and **conversation mining** (chat exports). Both store verbatim text in ChromaDB as drawers with wing/room metadata.

## Project mining

Scans a directory for files and chunks them by paragraph.

```bash
mempalace mine ~/projects/myapp
```

### What gets mined

Text-based files: `.py`, `.js`, `.ts`, `.md`, `.txt`, `.yaml`, `.json`, `.toml`, `.cfg`, `.ini`, `.html`, `.css`, `.sql`, `.sh`, `.rs`, `.go`, `.java`, `.rb`, `.php`, and similar.

### What gets skipped

- Directories in the default skip list: `.git`, `node_modules`, `__pycache__`, `.venv`, `venv`, `dist`, `build`, `.next`, `coverage`, `.mempalace`, and others (full list in `palace.py`)
- Files matching `.gitignore` patterns (disable with `--no-gitignore`)
- Binary files
- Files already mined (checked by source file path and modification time)

### Wing assignment

The wing defaults to the directory name. Override with `--wing`:

```bash
mempalace mine ~/projects/myapp --wing my-web-app
```

### Room assignment

Rooms are assigned based on the file's parent directory name, mapped through 70+ patterns in `room_detector_local.py`. For example, files in `src/auth/` get room `auth`, files in `docs/` get room `documentation`.

Run `mempalace init <dir>` first to preview and confirm room detection.

### Re-mining

Running `mine` on the same directory again skips files that haven't changed (checked by modification time). Modified files are re-mined. To force a full re-mine, delete the palace and start fresh.

### Options

```bash
mempalace mine <dir> [options]

--wing NAME              Wing name (default: directory name)
--no-gitignore           Don't respect .gitignore
--include-ignored PATHS  Always scan these paths even if gitignored (comma-separated or repeated)
--agent NAME             Your name, recorded on every drawer (default: mempalace)
--limit N                Max files to process (0 = all)
--dry-run                Show what would be filed without filing
--palace PATH            Override palace location
```

## Conversation mining

Parses chat exports and chunks by exchange pair (one user message + one assistant response).

```bash
mempalace mine ~/chats/ --mode convos
```

### Supported formats

| Format | File type | Detection |
|--------|-----------|-----------|
| Claude Code sessions | JSONL | `type: "human"/"assistant"` entries |
| Claude.ai export | JSON | `messages` or `chat_messages` array |
| ChatGPT export | JSON | `mapping` tree with `author.role` |
| Slack channel export | JSON | `type: "message"` entries |
| OpenAI Codex CLI | JSONL | `session_meta` + `event_msg` entries |
| Plain text | TXT | Lines starting with `>` = user turns |

Format detection is automatic. The normalizer (`normalize.py`) converts all formats to a standard transcript before chunking.

### Exchange-pair chunking

Conversations are split into exchange pairs: one user message + the following assistant response. Each pair becomes one drawer. This preserves the question-and-answer context that makes memories searchable.

### General extraction mode

The `--extract general` flag classifies each exchange into one of five memory types and assigns a hall:

```bash
mempalace mine ~/chats/ --mode convos --extract general
```

Memory types: `decision`, `preference`, `milestone`, `problem`, `emotional`. Each maps to a hall (`hall_facts`, `hall_preferences`, `hall_events`, `hall_advice`, `hall_discoveries`).

### Options

```bash
mempalace mine <dir> --mode convos [options]

--wing NAME              Wing name (default: directory name)
--extract MODE           exchange (default) or general (5 memory types)
--agent NAME             Your name (default: mempalace)
--limit N                Max files to process (0 = all)
--dry-run                Show what would be filed without filing
--palace PATH            Override palace location
```

## Splitting mega-files

Some export tools concatenate multiple sessions into one file. Split them before mining:

```bash
mempalace split ~/chats/
mempalace split ~/chats/ --dry-run              # preview
mempalace split ~/chats/ --min-sessions 3       # only split files with 3+ sessions
mempalace split ~/chats/ --output-dir ~/split/  # write to a different directory
```

The splitter detects session boundaries in the transcript and writes one file per session.

## Deduplication

MemPalace checks for duplicates before filing:

- **Project mining** skips files already mined (by source file path + modification time).
- **Conversation mining** skips files already mined (by source file path).
- **MCP `add_drawer`** uses a deterministic ID derived from wing + room + the first 100 characters of content, so upserting the same content is a no-op. Note: different content sharing the same first 100 characters will collide and be treated as `already_exists`.

For bulk deduplication of an existing palace, see the `dedup.py` module.
