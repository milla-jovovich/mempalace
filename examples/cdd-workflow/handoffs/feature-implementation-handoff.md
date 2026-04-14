# Handoff Capsule

## Header

- Title: Begin onboarding implementation after sprint 2 planning
- Date: 2026-03-21
- From: Planning actor
- To / Next actor: Implementation actor
- Project / Scope: `onboarding-service` account creation and email verification
- Stored at: `handoffs/feature-implementation-handoff.md`

## Current Goal

Implement account creation and email verification without introducing new
infrastructure dependencies this sprint.

## Current State

- planning is complete for sprint 2
- PostgreSQL has already been selected for session storage
- SendGrid is the approved email provider
- no implementation code has landed for the new onboarding flow yet

## Key Decisions Made

- Decision: keep email verification on the existing SendGrid path
  Reason: avoids a new provider and keeps this sprint focused

- Decision: use PostgreSQL-backed session state
  Reason: session durability and concurrent-write support matter more than minimal setup

## Important Sources / Artifacts

- `decisions/use-postgresql.md`
  Why it matters: captures the persistence tradeoffs and rejected alternatives

- `context-bundles/sprint-2-planning.md`
  Why it matters: defines the active goal, constraints, risks, and open questions

## Retrieval Hints

- Wings: `onboarding-service`
- Rooms or topics: `handoffs`, `planning`, `decisions`, `incidents`
- Search phrases:
  - `onboarding sprint 2 handoff`
  - `postgresql session storage decision`
  - `email verification planning`
- Important file names:
  - `feature-implementation-handoff.md`
  - `sprint-2-planning.md`
  - `use-postgresql.md`

## Open Questions

- should an unverified account be able to restart onboarding without creating a duplicate session?
- what inactivity timeout should end an in-progress onboarding session?

## Next Recommended Action

- implement account creation first
- wire email verification on the existing SendGrid integration second
- validate the full first-login redirect path before expanding scope

## Risks / Confidence

- Confidence: high
- Risks:
  - signup retries may create duplicate partial sessions if idempotency is not handled
  - email delivery delays could make the flow appear broken without good user feedback

## Refresh Status

- MemPalace refresh run after durable changes: yes
- Notes: refresh after updating this handoff so the next actor can retrieve it directly
