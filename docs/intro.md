---
layout: docs
title: Introduction
description: What MemPalace is, why it exists, and how the pieces fit together.
eyebrow: Getting Started
heading: Introduction
subtitle: Open-source, local-first AI memory. Store every conversation verbatim, organize it into a palace, make it searchable.
next:
  href: /quick-start
  label: Quick Start
toc:
  - { id: what,      label: What is MemPalace }
  - { id: problem,   label: The Problem }
  - { id: approach,  label: The Approach }
  - { id: pieces,    label: The Three Pieces }
  - { id: results,   label: Results }
  - { id: where,     label: Where to Next }
---

## What is MemPalace {#what}

MemPalace is an open-source memory system for AI. It runs on your machine,
stores every conversation you have with an AI verbatim, and organizes those
conversations into a searchable structure inspired by the ancient Greek method
of loci — the "memory palace."

**No API key.** No cloud. No subscription. Two Python dependencies total.

## The Problem {#problem}

Decisions happen in conversations now. Not in docs. Not in Jira. In
conversations with Claude, ChatGPT, Copilot. The reasoning, the tradeoffs, the
"we tried X and it failed because Y" — all trapped in chat windows that
evaporate when the session ends.

**Six months of daily AI use = 19.5 million tokens.** That's every decision,
every debugging session, every architecture debate. Gone.

<div class="table-wrap" markdown="1">

| Approach                       | Tokens loaded               | Annual cost         |
|--------------------------------|-----------------------------|---------------------|
| Paste everything               | 19.5M — doesn't fit         | Impossible          |
| LLM summaries                  | ~650K                       | ~$507/yr            |
| **MemPalace wake-up**          | **~170 tokens**             | **~$0.70/yr**       |
| **MemPalace + 5 searches**     | **~13,500 tokens**          | **~$10/yr**         |

</div>

## The Approach {#approach}

Other memory systems try to fix this by letting the AI decide what's worth
remembering. It extracts _"user prefers Postgres"_ and throws away the
conversation where you explained _why_.

MemPalace takes the opposite approach:

> **Store everything. Then make it findable.**
{: .callout}

No AI decides what matters. You keep every word. The structure does the
finding.

## The Three Pieces {#pieces}

MemPalace is three ideas working together:

1. **[The Palace]({{ '/palace' | relative_url }})** — conversations organized into wings, halls, rooms, closets, and drawers. A structure that boosts retrieval by **34%**.
2. **[AAAK Dialect]({{ '/aaak' | relative_url }})** — a lossless shorthand designed for AI agents. 30x compression, readable by any text-reading LLM without a decoder.
3. **[Knowledge Graph]({{ '/knowledge-graph' | relative_url }})** — temporal entity-relationship triples with validity windows. Like Zep's Graphiti, but local and free.

Plus integrations to make your AI actually use them:

- **[MCP Server]({{ '/mcp' | relative_url }})** — 19 tools that let Claude, Cursor, and any MCP-compatible AI read and write the palace automatically.
- **[Auto-Save Hooks]({{ '/hooks' | relative_url }})** — for Claude Code and Codex CLI. No manual save commands.
- **[Specialist Agents]({{ '/agents' | relative_url }})** — focused lenses on your data, each with their own wing and diary.

## Results {#results}

Tested against the hardest academic benchmarks for AI memory:

<div class="table-wrap" markdown="1">

| Benchmark                            | Score          | API required     |
|--------------------------------------|----------------|------------------|
| **LongMemEval R@5** (raw)            | **96.6%**      | None             |
| **LongMemEval R@5** (hybrid + Haiku) | **100%**       | Optional         |
| **ConvoMem**                         | **92.9%**      | None             |
| **LoCoMo R@10** (with Sonnet)        | **100%**       | Optional         |

</div>

The **96.6% raw** is the highest published LongMemEval score that requires no
API key, no cloud, and no LLM at any stage. See
[Benchmarks]({{ '/benchmarks' | relative_url }}) for the full story.

## Where to Next {#where}

- **Want to install and try it?** → [Quick Start]({{ '/quick-start' | relative_url }})
- **Want to understand the architecture?** → [The Palace]({{ '/palace' | relative_url }})
- **Want to wire it into Claude Code?** → [MCP Server]({{ '/mcp' | relative_url }})
- **Want to see the numbers?** → [Benchmarks]({{ '/benchmarks' | relative_url }})
