# Example: CDD Workflow For Engineering Memory

This example shows one practical way to use MemPalace for software engineering work.

It is shaped by a Context-Driven Development workflow, but the example itself is meant
to be generic and copyable. You do not need to adopt CDD to use this layout.

The goal is simple:

- keep durable project artifacts in repo paths
- index them with MemPalace
- let the next actor resume from retrieval instead of replaying chat history

## What is in this example

```text
examples/cdd-workflow/
|- mempalace.yaml
|- README.md
|- decisions/
|  `- use-postgresql.md
|- context-bundles/
|  `- sprint-2-planning.md
`- handoffs/
   `- feature-implementation-handoff.md
```

## Why this layout works

The room layout keeps different kinds of engineering memory separate enough to retrieve
cleanly:

| Room | What goes in it | When it helps most |
| --- | --- | --- |
| `decisions` | Architecture decisions, tradeoffs, rejected approaches | Planning, implementation |
| `planning` | Sprint goals, constraints, open questions, context bundles | Planning |
| `handoffs` | Bounded implementation handoffs and resume notes | Implementation, cold start |
| `incidents` | Bugs, root-cause notes, workarounds | Planning, validation |
| `validation` | Acceptance criteria, release checks, known failure modes | Validation |

## Suggested workflow

### Outgoing actor

1. Save durable artifacts in repo paths
2. Update the relevant decision record, context bundle, or handoff note
3. Refresh MemPalace after those artifacts exist

### Incoming actor

1. Search for the latest handoff
2. Use the handoff's retrieval hints to pull related memory
3. Open the authoritative files named in the handoff
4. Validate the current state before acting

This keeps the handoff grounded in durable sources instead of relying on one chat log.

## Example retrieval by stage

### Planning

- retrieve `planning` for active goals and constraints
- retrieve `decisions` for prior tradeoffs
- retrieve `incidents` for known failure modes

### Implementation

- retrieve `handoffs` for current workstream state
- retrieve `decisions` when changing sensitive areas
- retrieve `planning` when scope and constraints are still active

### Validation

- retrieve `validation` for release checks and expected outcomes
- retrieve `incidents` for regression checks
- retrieve `decisions` when validating tradeoff-sensitive behavior

## Handoff capsule format

The handoff example in `handoffs/feature-implementation-handoff.md` uses a simple structure:

- Header
- Current Goal
- Current State
- Key Decisions Made
- Important Sources / Artifacts
- Retrieval Hints
- Open Questions
- Next Recommended Action
- Risks / Confidence
- Refresh Status

That is enough for another human or agent to resume productively without reading the
entire previous session.

## How to try it

1. Copy `mempalace.yaml` into a project root
2. Add a few durable artifacts like the samples in this directory
3. Run `mempalace mine .`
4. Query with `mempalace search "postgresql decision"` or through MCP

For MCP setup, see [../mcp_setup.md](../mcp_setup.md).

## What this example demonstrates

The value is not just search.

The value is that project memory becomes:

- durable
- stage-aware
- small enough to retrieve selectively
- usable across human and agent handoffs

That is where MemPalace becomes especially useful for real engineering work.
