# ADR-0001: FastAPI + MongoDB stay

**Status:** Accepted
**Date:** 2026-05-16
**Deciders:** RamC (architect)
**Ticket:** P0-01

## Context

The v2 architecture migration plan (approved 2026-05-16) reshapes the codebase along clean-architecture lines and adds a persona-shaped BFF. A reasonable question at the start of any structural migration is: *should we change the language and database too?* This ADR closes that question explicitly so subsequent work does not relitigate it.

Today the backend is **Python 3.12 + FastAPI + MongoDB (Motor async driver)**. The migration is happening on a small team (effectively one engineer). Phase 5 has just shipped — Stripe checkout + capacity-aware webhook, waitlist FIFO promotion, Firebase Auth hardening, coach today endpoint. Those flows are live and stable.

## Decision

Keep **FastAPI + MongoDB** for v2. The migration is structural, not technological.

- All v2 code lives under `backend/v2/` and uses the same FastAPI app process and the same MongoDB cluster as legacy.
- The driver stays Motor (async). Pydantic v2 stays for input validation and DTO shaping.
- No language switch. No database switch. Both are deferred indefinitely; revisiting requires a superseding ADR.

## Options Considered

### Option A: Stay on FastAPI + MongoDB (chosen)

| Dimension | Assessment |
|---|---|
| Complexity | Low — no migration ceremony |
| Cost | Low — no parallel infra |
| Scalability | Sufficient for a single academy and the foreseeable multi-tenant path |
| Team familiarity | High — 100% of existing knowledge transfers |
| Risk | Low |

**Pros:**
- Zero throwaway work — every line of v2 code is shaped by the architecture, not by porting friction.
- Stripe webhooks, Firebase Admin SDK, and Motor are already integrated and battle-tested in Phase 5.
- Mongo's document shape fits the current aggregates well (sessions, enrollments, payments) and the planned outbox/idempotency patterns work cleanly inside a Mongo transaction.
- Pydantic v2 + FastAPI's OpenAPI generation drives the `openapi-typescript` typed-client pipeline planned for the frontend.

**Cons:**
- Mongo joins are application-side. Acceptable today because reads are aggregate-rooted; if cross-aggregate analytics gets heavy, we'd want a read store. Out of scope.
- Python has higher per-request CPU cost than a compiled language. Not the bottleneck at current scale; well within budget.

### Option B: Rewrite to TypeScript (Node + Fastify or NestJS) + Postgres

| Dimension | Assessment |
|---|---|
| Complexity | High — full backend rewrite |
| Cost | 4–6 weeks lost to porting before any v2 value lands |
| Scalability | Comparable |
| Team familiarity | Lower for backend; the frontend is TS so there's a code-sharing argument |
| Risk | High |

**Pros:**
- Shared types between backend and frontend without a generation step.
- Postgres gives real transactions, joins, and a mature ecosystem of migration tooling.

**Cons:**
- The migration plan is already large (10–11 weeks of work). Adding a language port doubles the timeline and risk for benefits that are mostly ergonomic.
- We would lose Phase 5's working Stripe/Firebase wiring and pay to recreate it.
- The architect review explicitly called out that this is **not a rewrite**. A language port is a rewrite by another name.

### Option C: Rewrite to Go + Postgres

| Dimension | Assessment |
|---|---|
| Complexity | High |
| Cost | Highest porting cost (smallest existing Go knowledge on the team) |
| Scalability | Higher ceiling |
| Team familiarity | Low |
| Risk | High |

**Pros:** Performance ceiling, deployment simplicity.
**Cons:** Same as Option B, amplified by smaller team familiarity. Rejected on those grounds alone.

### Option D: Stay Python, migrate Mongo → Postgres only

| Dimension | Assessment |
|---|---|
| Complexity | Medium-high |
| Cost | 2–3 weeks of migration + data dual-write window |
| Scalability | Comparable for our workloads |
| Team familiarity | Medium |
| Risk | Medium |

**Pros:** Real transactions and joins; better fit for some reporting workloads.
**Cons:** The cost of dual-writing during migration is real and the current Mongo schema serves us well. The plan's data-ownership map and outbox pattern do not depend on a relational store. Defer to a future ADR if reporting grows independent rules.

## Trade-off Analysis

The forcing function is **risk budget**. The migration plan already commits to a Phase 0 + four-wave path. Adding a language or database swap on top of that compounds risk multiplicatively, not additively. Every wave's exit gate (golden-master parity, Stripe fixture replay, security matrix coverage) becomes harder to meet if the runtime is also new.

The case for changing the stack is largely ergonomic (shared types, joins). The ergonomic cost is real but bounded by `openapi-typescript` generation (P0-19) and disciplined aggregate-rooted reads.

## Consequences

**Becomes easier:**
- v2 work starts immediately; no porting prerequisite.
- Existing Stripe/Firebase/Resend integrations are reused in `infrastructure/` adapters.
- Mongo transactions support the outbox pattern (P0-13) cleanly.

**Becomes harder:**
- Cross-aggregate reporting will stay application-side or require a future read store.
- Shared types between backend and frontend require the OpenAPI generation pipeline to be reliable (P0-19 makes that a CI gate).

**To revisit:**
- If reporting/analytics grows independent rules (a Finance context with cross-aggregate aggregates, for example), an ADR for a read store may follow.
- If multi-tenant scale demands schema-level isolation, a Postgres-per-tenant pattern may need a fresh ADR.

## Action Items

1. [x] Reject TS/Postgres, Go/Postgres, Python/Postgres-only options.
2. [ ] Proceed with `backend/v2/` skeleton under FastAPI + Mongo (P0-11).
3. [ ] Set up `openapi-typescript` generation (P0-19) so the ergonomic gap is closed.
