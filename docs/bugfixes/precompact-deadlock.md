# PreCompact Hook Deadlock

**Status:** Fixed on `develop`
**Affects:** All MemPalace versions through v3.3.0 when used with the Claude Code harness
**Symptom:** Session appears frozen near the context limit. `/compact` has no effect. `~/.mempalace/hook_state/hook.log` shows repeated `PRE-COMPACT triggered for session …` entries, many per minute, with no intervening `Stop` hook activity.

## TL;DR

`hook_precompact()` in `mempalace/hooks_cli.py` unconditionally returned `{"decision": "block", "reason": PRECOMPACT_BLOCK_REASON}`. In the Claude Code harness, `decision: block` on a PreCompact hook **cancels the compaction** and feeds the `reason` string back to the model as an instruction. The model then tries to save memory, the response ends, and Claude Code notices the context is still over the limit — so it fires PreCompact again. The hook blocks again. The loop never terminates on its own, and manual `/compact` was also blocked because the hook ignored the `trigger` field that distinguishes user-initiated compaction from automatic.

The fix adds two guards to `hook_precompact()`:

1. **Manual trigger passes through.** If `data["trigger"] == "manual"` (i.e. the user ran `/compact`), return `{}` immediately. The user asked for compaction; never block them.
2. **Per-session exchange-count guard.** Record the human-message count at the moment we block in `~/.mempalace/hook_state/{session_id}_precompact_blocked_at`. On re-fire, if the current count is still `<= last_blocked_at`, the save already ran — delete the state file and return `{}`, letting compaction proceed. A fresh user message advances the count and re-arms a single block for the next round.

## How the deadlock was observed

One affected session in the wild (`~/.mempalace/hook_state/hook.log`):

```
[15:27:02] Session 082d4cc3-…: 173 exchanges, 14 since last save
[16:13:45] PRE-COMPACT triggered for session 082d4cc3-…
[16:16:31] PRE-COMPACT triggered for session 082d4cc3-…
[16:18:56] PRE-COMPACT triggered for session 082d4cc3-…
[16:21:29] PRE-COMPACT triggered for session 082d4cc3-…
[16:22:05] PRE-COMPACT triggered for session 082d4cc3-…
[16:23:57] PRE-COMPACT triggered for session 082d4cc3-…
[16:28:05] PRE-COMPACT triggered for session 082d4cc3-…
```

Eight PreCompact fires in 15 minutes. Zero `Stop` hook entries in between, because the session never got control back to a clean "response done" state — every time the model finished writing memory, Claude Code immediately re-attempted compaction, which immediately re-fired the hook, which immediately re-blocked.

Invoking `/compact` manually did not help: Claude Code sends the same `PreCompact` event for manual compactions (just with `trigger: "manual"` in the payload), and the old code read neither field.

## Root cause in the old code

```python
# mempalace/hooks_cli.py  (before the fix)
def hook_precompact(data: dict, harness: str):
    """Precompact hook: always block with comprehensive save instruction."""
    parsed = _parse_harness_input(data, harness)
    session_id = parsed["session_id"]

    _log(f"PRE-COMPACT triggered for session {session_id}")

    # ... optional auto-ingest ...

    # Always block -- compaction = save everything
    _output({"decision": "block", "reason": PRECOMPACT_BLOCK_REASON})
```

Compare to the Stop hook, which already had a loop guard (`stop_hook_active`, read from the harness payload) so that a save cycle triggered by a previous block would pass through instead of re-blocking. The PreCompact hook had no equivalent. Claude Code does not provide a `precompact_hook_active` flag, so the guard has to be stateful on the MemPalace side.

## The fix

`hook_precompact()` now reads two extra fields from the hook payload:

- `trigger` — Claude Code sets this to `"manual"` when the user ran `/compact` and `"auto"` when the harness fired PreCompact on its own.
- `transcript_path` — already parsed by `_parse_harness_input`, used to count human messages for the guard.

```python
def hook_precompact(data: dict, harness: str):
    parsed = _parse_harness_input(data, harness)
    session_id = parsed["session_id"]
    transcript_path = parsed["transcript_path"]
    trigger = str(data.get("trigger", "auto")).lower()

    _log(f"PRE-COMPACT triggered for session {session_id} (trigger={trigger})")

    # Guard 1: manual /compact must never be blocked.
    if trigger == "manual":
        _log("PRE-COMPACT manual trigger -- allowing compaction")
        _output({})
        return

    # Guard 2: deadlock guard.
    exchange_count = _count_human_messages(transcript_path)
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    state_file = STATE_DIR / f"{session_id}_precompact_blocked_at"
    last_blocked_at = -1
    if state_file.is_file():
        try:
            last_blocked_at = int(state_file.read_text().strip())
        except (ValueError, OSError):
            last_blocked_at = -1

    if last_blocked_at >= 0 and exchange_count <= last_blocked_at:
        _log(
            f"PRE-COMPACT already blocked at exchange {last_blocked_at} "
            f"(now {exchange_count}) -- allowing compaction to prevent deadlock"
        )
        try:
            state_file.unlink()
        except OSError:
            pass
        _output({})
        return

    try:
        state_file.write_text(str(exchange_count), encoding="utf-8")
    except OSError:
        pass

    # ... optional auto-ingest unchanged ...

    _output({"decision": "block", "reason": PRECOMPACT_BLOCK_REASON})
```

### Behavior after the fix

| Scenario                                                  | Before    | After               |
| --------------------------------------------------------- | --------- | ------------------- |
| User runs `/compact` (`trigger="manual"`)                 | blocked → deadlock | passes through (`{}`) |
| 1st auto PreCompact after save threshold crossed          | blocks for save    | blocks for save (unchanged) |
| 2nd auto PreCompact, no new user message since            | blocks again → loop | passes through (`{}`) |
| Auto PreCompact after a new user message arrives          | blocks again → loop | blocks once more (guard re-armed) |

## Escape hatch for a frozen session (pre-fix or during upgrade)

If you are currently stuck in the loop on an unpatched MemPalace:

```bash
# Unblock the guard state (only exists on patched versions, harmless otherwise)
rm -f ~/.mempalace/hook_state/*_precompact_blocked_at

# Then run manual compact, which the patched hook passes through.
/compact
```

If you are on an **unpatched** version, the only reliable workaround is to exit the Claude Code session and start a new one with `claude --continue`. No amount of `/compact` will break the loop until the hook is replaced.

## Verifying you have the fix

```bash
grep -n "trigger" "$(python3 -c 'import mempalace.hooks_cli as m; print(m.__file__)')" \
  | grep -q 'hook_precompact\|"manual"' && echo "patched" || echo "NOT patched"
```

Or run the smoke test directly:

```bash
echo '{"session_id":"t","transcript_path":"/nonexistent","trigger":"manual"}' \
  | python3 -m mempalace hook run --hook precompact --harness claude-code
# Expect: {}

echo '{"session_id":"t","transcript_path":"/nonexistent","trigger":"auto"}' \
  | python3 -m mempalace hook run --hook precompact --harness claude-code
# Expect: {"decision":"block", ...}

echo '{"session_id":"t","transcript_path":"/nonexistent","trigger":"auto"}' \
  | python3 -m mempalace hook run --hook precompact --harness claude-code
# Expect: {}  (deadlock guard released)

rm -f ~/.mempalace/hook_state/t_precompact_blocked_at
```

## Tests

Unit coverage lives in `tests/test_hooks_cli.py`:

- `test_precompact_first_fire_blocks` — baseline "blocks for save" behavior is preserved.
- `test_precompact_manual_trigger_passes_through` — guard 1.
- `test_precompact_deadlock_guard_allows_refire` — guard 2 (the main regression test for this bug).
- `test_precompact_new_human_message_rearms_block` — guard 2 does not over-suppress: a fresh user turn must still get one save-block.

## Why not drop PreCompact blocking altogether?

PreCompact blocking is the feature that forces a thorough save right before detailed context is lost. Removing it would silently degrade memory quality at exactly the moment it matters most — long sessions where compaction is frequent. The fix preserves that guarantee (one save per new user turn) while removing the failure mode where the same save-block replays forever.
