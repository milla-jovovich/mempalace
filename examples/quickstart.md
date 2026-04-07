# Getting started with MemPalace

This walkthrough uses the tiny sample in [`demo_project/`](demo_project/) — everyday notes (family plans, a trip, reminders) — so you can run **mine → search → status** in a few minutes. Everything stays on your machine; no API keys.

## 1. Install

From the repo root (or use `pip install mempalace`):

```bash
pip install -e .
```

## 2. Try the bundled demo (no `init` prompts)

`demo_project` already includes a `mempalace.yaml`, so you can mine immediately.

**Optional — isolated palace** (does not touch your default `~/.mempalace/palace`):

```bash
export MEMPALACE_PALACE_PATH=/tmp/mempalace_getting_started
```

**Mine** the sample files into the palace:

```bash
mempalace mine examples/demo_project
```

You should see something like this:

```console
=======================================================
  MemPalace Mine
=======================================================
  Wing:    everyday_notes
  Rooms:   journal, plans, general
  Files:   2
  Palace:  /Users/[username]/.mempalace/palace
───────────────────────────────────────────────────────

  ✓ [   1/2] weekend.md                                         +1
  ✓ [   2/2] summer_trip.md                                     +1

=======================================================
  Done.
  Files processed: 2
  Files skipped (already filed): 0
  Drawers filed: 2

  By room:
    journal              1 files
    plans                1 files

  Next: mempalace search "what you're looking for"
=======================================================
```

**Search** for words that appear in the sample notes:

```bash
mempalace search "cabin"
mempalace search "birthday"
```

**See what was stored:**

```bash
mempalace status
```

**Narrow search** to one wing or room (names come from your `mempalace.yaml` and metadata):

```bash
mempalace search "vet" --wing everyday_notes --room journal
```

**Wake-up context** (compact L0 + L1 text you can paste into a model prompt):

```bash
mempalace wake-up
mempalace wake-up --wing everyday_notes
```

**Optional — AAAK compression preview** (read-only dry run):

```bash
mempalace compress --wing everyday_notes --dry-run
```

## 3. Your own project (first-time setup)

For a real directory, **initialize** rooms from folder layout and entity hints (interactive prompts — press Enter to accept defaults):

```bash
mempalace init ~/projects/my_app
mempalace mine ~/projects/my_app
```

Conversation exports (Claude, ChatGPT, Slack, etc.):

```bash
mempalace mine ~/path/to/exports --mode convos --wing my_app
```

Richer convo extraction (decisions, milestones, problems, …):

```bash
mempalace mine ~/path/to/chats --mode convos --extract general
```

Huge concatenated transcripts: run `mempalace split` on the folder **before** `mine` (see `mempalace split --help`).

## 4. From Python

```python
import os
from mempalace.searcher import search_memories
from mempalace.layers import MemoryStack

palace = os.environ.get("MEMPALACE_PALACE_PATH", os.path.expanduser("~/.mempalace/palace"))

out = search_memories("summer", palace_path=palace, n_results=3)
if "error" in out:
    print(out["error"])
else:
    for hit in out["results"]:
        print(hit["wing"], hit["room"], hit["similarity"])
        print(hit["text"][:500])
        print("---")

stack = MemoryStack(palace_path=palace)
print(stack.wake_up(wing="everyday_notes"))
```

## 5. One-command runner

From the **repository root** (after `pip install -e .`):

```bash
python examples/quickstart_demo.py --isolated
```

This mines `examples/demo_project`, runs `status`, and runs a sample `search`.

## Next steps

- Main README: [../README.md](../README.md) — MCP setup, benchmarks, palace model.
- CLI overview: `mempalace --help` and `mempalace <command> --help`.
