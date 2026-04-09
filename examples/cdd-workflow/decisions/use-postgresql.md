# Decision: Use PostgreSQL For Session Storage

**Status:** Accepted
**Date:** 2026-03-15

## Context

The onboarding service needs durable session state that supports concurrent writes from
multiple service instances and can be queried by user ID and session ID.

SQLite was the initial candidate because it adds no infrastructure, but it cannot handle
concurrent writes from more than one process.

Redis was considered for its speed, but it adds an operational dependency we are not
ready to take on and does not provide durability without extra persistence setup.

## Decision

Use PostgreSQL 15 with pgbouncer for connection pooling.

## Rationale

- handles concurrent writes correctly without application-level locking
- fits the team's existing migration and operational workflow
- supports the query patterns already expected in the service
- keeps connection counts manageable through pgbouncer

## Tradeoffs accepted

- adds infrastructure complexity compared to SQLite
- requires a running PostgreSQL instance in development
- slightly increases setup cost for new contributors

## Rejected alternatives

- SQLite: cannot handle concurrent writes from multiple processes
- Redis: fast, but adds persistence and ops complexity we are not ready for
- In-memory store: no durability, rules out horizontal scaling

## Retrieval note

Filed under `onboarding-service / decisions`.
Retrieve during planning and implementation when auth or session storage is in scope.
