# Tool Output Capture in Conversation Mining

**Date**: 2026-04-10
**Status**: Approved
**Scope**: `mempalace/normalize.py` — Claude Code JSONL only

## Problem

`_extract_content()` in `normalize.py` only extracts `type: "text"` blocks from Claude Code JSONL transcripts. Tool use blocks (847 per typical session) and tool result blocks (847 matching) are silently dropped during normalization.

This loses unique findings that exist nowhere else in the codebase or palace:
- Bash command output (firmware probes, build errors, test results, runtime behavior)
- External API responses
- Runtime diagnostics and system state

## Decision: Selective Capture by Tool Type

Not all tool output has equal value. File contents from `Read` are already mined as project drawers. Git diffs from `Edit` are in version history. But Bash output contains unique runtime findings that are irreproducible from code alone.

Strategy: **capture aggressively for Bash, breadcrumb-only for everything else.**

## What Changes

All changes are in `normalize.py`, within `_try_claude_code_jsonl()` and `_extract_content()`. No new modules.

### Tool Use Formatting

Tool invocations are formatted inline with assistant text:

| Tool | Format |
|------|--------|
| Bash | `[Bash] <command>` (command truncated at 200 chars) |
| Read | `[Read <path>:<offset>-<offset+limit>]` |
| Grep | `[Grep] <pattern> in <path/glob>` |
| Edit | `[Edit <path>]` |
| Write | `[Write <path>]` |
| Other | `[ToolName] <first 200 chars of JSON input>` |

### Tool Result Extraction Strategies

| Tool | Strategy | Rationale |
|------|----------|-----------|
| Bash | First 20 lines + last 20 lines, gap marker if middle truncated | Unique findings live here; errors appear at tail |
| Read | Omitted (path in tool_use is sufficient) | Content already mined as project files |
| Grep/Glob | Query + matched file list, cap 20 matches | Matches are the finding; context is reproducible |
| Edit/Write | Omitted (path in tool_use is sufficient) | Actual diff is in git history |
| Other (MCP, etc.) | First 2KB, truncate with `... [truncated, N chars]` | Safe default for unknown tools |

### Inline Formatting Example

```
Let me check the firmware version.
[Bash] lsusb | grep -i razer
→ Bus 002 Device 005: ID 1532:0e05 Razer USA, Ltd Razer Kiyo Pro
Then I ran the XU probe...
```

- Tool results are prefixed with `→ `
- Bash head+tail gap marker: `→ ... [N lines omitted] ...`
- Truncation marker: `→ ... [truncated, N chars]`

### Tool Use → Tool Result Matching

Claude Code JSONL links tool calls via `tool_use_id` (on `tool_result` blocks) matching `id` (on `tool_use` blocks). Within `_try_claude_code_jsonl()`, a dict maps `{tool_use_id: tool_name}` as blocks are processed, so when a `tool_result` is encountered, the correct extraction strategy is applied.

## What Doesn't Change

- `convo_miner.py` — chunker sees normal transcript text, no changes needed
- `_messages_to_transcript()` — unchanged
- Other format parsers (Codex, ChatGPT, Slack, Claude.ai) — untouched
- `thinking` blocks — still ignored (redacted/empty in JSONL, only signature remains)
- `image` blocks — still ignored (binary, can't text-mine)

## Testing

New test cases added to existing normalize test file:
- Mock JSONL with tool_use/tool_result content blocks
- Verify Bash head+tail strategy (short output, long output with gap)
- Verify Read produces path-only breadcrumb
- Verify Grep produces query + match list
- Verify Edit/Write produce path-only breadcrumb
- Verify fallback truncation for unknown tools
- Verify tool_use → tool_result ID matching across message boundaries
- Verify existing text-only extraction is unaffected

## Future Work

- Codex JSONL tool output (when needed)
- Copilot CLI / Gemini CLI parsers (no parsers exist yet; tool output handling built in from the start)
