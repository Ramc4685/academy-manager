# ADR-0005: Clean-architecture-lite monolith, not microservices

**Status:** Accepted
**Date:** 2026-05-16
**Deciders:** RamC (architect)
**Ticket:** P0-05

## Context

The current backend is a procedural FastAPI monolith — routes call Mongo directly, mix business logic with HTTP concerns, and embed Stripe/Firebase coupling inside handlers. The architect review accepted "DDD-lite" as the structural target: bounded contexts, aggregates, repositories, application services, and domain events. The question is *how strict* and *how distributed*.

The plan defines four bounded contexts (Identity, Enrollment, Billing, Coaching). Three personas. One team. One database.

## Decision

Adopt **clean-architecture-lite** inside a single deployable monolith. No microservices. No event sourcing. No CQRS read models.

The architecture has four layers per bounded context, with a strict inward dependency rule:

```
interfaces ─────► application ─────► domain
                       ▲
                       │
                  infrastructure
```

- **Domain** — pure Python. Aggregates, value objects, domain events, domain errors. Imports only from the standard library and the context's own domain submodules.
- **Application** — use cases (one file per command or query), ports (Protocols/ABCs), application-layer DTOs. Imports from `domain/`. Defines the interfaces that infrastructure implements.
- **Infrastructure** — Mongo repositories (implementing `application/ports.py` Protocols), Stripe gateway, Firebase Admin, Resend email. Imports from `application/` and `domain/`.
- **Interfaces** — FastAPI routes, persona-shaped view DTOs, HTTP error handlers. Imports from `application/`. **Never** imports from `infrastructure/` directly — composition root wires them.

Cross-context communication is via **domain events** (in-process dispatcher with a Mongo outbox, ADR-0009-equivalent in `docs/event-rules.md`), never direct DB writes.

## Layering Rules (enforced)

`import-linter` rules in `pyproject.toml` enforce the contract:

1. `backend/v2/contexts/*/domain/` may import only stdlib, `pydantic`, and `backend/v2/contexts/<same-context>/domain/`.
2. `backend/v2/contexts/*/application/` may import from its own `domain/` and stdlib/typing/pydantic. **Not** from any `infrastructure/` or `interfaces/`.
3. `backend/v2/contexts/*/infrastructure/` may import from its own `domain/` + `application/`, and from `shared/`. **Not** from `interfaces/`.
4. `backend/v2/interfaces/<persona>/` may import from `contexts/*/application/` and `shared/`. **Not** from any `contexts/*/infrastructure/` or `contexts/*/domain/` directly (must go through application).
5. **No cross-context imports between `contexts/`.** `contexts/coaching/` may not import `contexts/enrollment/`. Coupling happens via events through `shared/events/`, or via the interface layer composing both.
6. `shared/tenancy/` is the only place that references `academy_id` outside `infrastructure/` (ADR-0006).

Violations fail CI.

## Options Considered

### Option A: Clean-architecture-lite monolith (chosen)

| Dimension | Assessment |
|---|---|
| Complexity | Medium — four-layer discipline takes adjustment |
| Cost | One-time learning + sustained discipline; tooling enforces it |
| Scalability | Sufficient for current and foreseeable scale |
| Reversibility | Each context can be extracted to its own service later (ADR-0003 lift-out criteria) |

**Pros:**
- Domain logic is pure and testable without I/O.
- Repositories abstract Mongo; swapping stores is a per-context change.
- Use cases compose without HTTP context — they are callable from tests, scripts, future event handlers.
- Layering is mechanically enforced; no architecture-by-vibes.
- Each context is independently understandable.

**Cons:**
- More files per slice than the legacy "one router calls Mongo" style.
- Discipline must hold or the layering decays. Mitigated by import-linter in CI.

### Option B: Microservices (one service per bounded context)

**Pros:** True independence, polyglot opportunity, scale per context.

**Cons:**
- Operational cost is enormous relative to team and scale: four deploys, four observability surfaces, four release pipelines, service discovery, inter-service auth, distributed tracing.
- Cross-context transactions become sagas. Stripe webhook ↔ enrollment confirmation is a saga in microservices; it's a synchronous outbox-backed event handler in the monolith.
- Premature decomposition is the most common cause of architecture failure at our scale. Rejected.

### Option C: Event sourcing + CQRS

**Pros:** Perfect audit trail; flexible read models; time-travel queries.

**Cons:**
- We don't have the read-side complexity that justifies the projection cost.
- Migrating live data to event-sourced aggregates is its own multi-month project.
- The audit trail we need (Stripe payments, attendance changes) can be served by domain events + an audit collection without event sourcing.
- Rejected as overkill.

### Option D: Hexagonal/ports-and-adapters without DDD ceremony

This is effectively what we're doing, with "context" as the boundary. **Same as Option A in practice** — clean-architecture-lite and hexagonal-without-DDD-ceremony differ in terminology, not in structure. The ADR uses the four-layer naming because it's the most direct framing for the team.

### Option E: Layered architecture, no aggregates

**Pros:** Less ceremony; one DTO type per concept.

**Cons:** The current codebase is essentially this with no service layer. The pain points (god routers, missing invariants, Stripe-inside-handlers) are direct consequences. Going back to it solves nothing.

## Trade-off Analysis

The real choice is between **structured-monolith (Option A) and distributed-monolith disguised as microservices (Option B)**. Microservices look attractive on paper for the "clean contexts" goal but pay enormous operational cost for benefits we don't need yet. Option A delivers the same architectural intent with a tenth of the operational overhead.

Event sourcing and CQRS are rejected for the same reason: they solve problems we don't have.

## Consequences

**Becomes easier:**
- Per-context unit testing (domain is pure).
- Per-context refactoring (boundaries are explicit).
- Adding a new persona's BFF (compose existing use cases).
- Future extraction to a service (each context is self-contained).
- Stripe / Firebase / Resend mocking (port + adapter).

**Becomes harder:**
- File count grows. A simple feature might touch four files instead of one. This is the trade — explicit boundaries cost lines of code, save weeks of debugging.
- New contributors must learn the layering rule before contributing. ADR + a `backend/v2/README.md` covers this.
- Quick hacks ("just call Mongo from the route") are impossible. Good.

**To revisit:**
- A context with persistent independent scaling needs may be extracted to a service per ADR-0003's lift-out criteria.
- If layering enforcement becomes a friction tax disproportionate to value (e.g., for very small admin-only contexts), specific contexts may be granted exceptions documented in their own ADRs.

## Action Items

1. [x] Reject microservices, event sourcing, and flat-layered options.
2. [ ] Configure `import-linter` with the six rules above (P0-11).
3. [ ] Document the layering in `backend/v2/README.md` with one example slice (the Identity context built in W1A-02 serves as the canonical example).
4. [ ] Every new context must add its own layer-conformance smoke test.
