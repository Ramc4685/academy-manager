# ADR-0003: BFF lives inside the backend (one process)

**Status:** Accepted
**Date:** 2026-05-16
**Deciders:** RamC (architect)
**Ticket:** P0-03

## Context

The plan introduces a Backend-for-Frontend layer so that admin, coach, and parent clients each call persona-shaped endpoints (`/api/v2/admin/*`, `/api/v2/coach/*`, `/api/v2/parent/*`). The question is whether this layer is a separate deployable process (the classic "BFF per client") or a presentation slice inside the existing FastAPI app.

Today there is one FastAPI process. There are three client surfaces (admin web, coach mobile-web, parent mobile-web), and there will likely remain three for the foreseeable future. The migration plan classifies this as a vertical-slice refactor, not a distributed-systems redesign.

## Decision

The BFF is a **structural layer inside the single FastAPI process**, not a separately deployed service. It lives at `backend/v2/interfaces/<persona>/` and composes use cases from the four bounded contexts.

- One FastAPI process serves all three persona route groups.
- Persona separation is enforced by directory layout, route prefix, and per-persona view DTOs — not by network boundary.
- Domain code knows nothing about HTTP or personas. The interfaces layer is the only place persona-shaping lives.

The directory layout is **persona first, context second**:

```
interfaces/
├── coach/
│   ├── today_routes.py
│   ├── attendance_routes.py
│   └── views.py
├── parent/
│   ├── onboarding_routes.py
│   ├── payment_routes.py
│   └── views.py
└── admin/
    ├── enrollment_routes.py
    ├── billing_routes.py
    └── views.py
```

## Options Considered

### Option A: BFF as a layer inside the monolith (chosen)

**Pros:**
- Zero new deploy units. No new infra to learn.
- Composition is trivial — a coach route imports use cases from `contexts.enrollment` and `contexts.coaching` and stitches a `views.coach.TodayResponse`.
- Persona-shaping happens close to the domain; one engineer can hold a vertical slice in their head.
- The directory layout is lift-out-friendly: the day persona BFFs need independent deploys, `interfaces/coach/` lifts cleanly into a new app sharing the same `contexts/` package.

**Cons:**
- All personas share one deploy. A bad admin release affects coaches. Mitigated by canary + feature flags at the edge.
- No per-persona scaling story. Not a real constraint at current scale.

### Option B: Three deployed BFFs + one internal domain API

**Pros:**
- Independent deploys per persona. Coach mobile can release on its own cadence.
- Each BFF can tune its own caching, language, runtime.

**Cons:**
- We don't have the scale, team size, or release pressure to justify three additional deploy units.
- Domain API contract becomes a public(-ish) seam, requiring more rigor than the current internal API call.
- Operational cost (three more deployments, three more on-call surfaces) is non-trivial.
- Coach mobile latency over a network hop to the domain API is worse than a local function call.

Rejected on premature distribution — not because it's wrong, but because it's too early.

### Option C: GraphQL gateway

**Pros:**
- One endpoint, persona-flexible queries on the client.
- Strong typing across the boundary.

**Cons:**
- Three personas with stable, known shapes don't benefit from query flexibility. The flexibility cost (caching is harder, depth/complexity limits, N+1 mitigation, persisted queries for caching) outweighs the gain.
- Adds a runtime layer between client and domain. We already have one (FastAPI). Layering another buys little.
- No team experience with a production GraphQL gateway. Rejected.

### Option D: One generic API + client-side shaping

Status quo. The plan rejects this in its premise: the current undifferentiated `/api/*` is the problem we're solving.

## Trade-off Analysis

The core trade-off is **distribution boundary vs. complexity**. Option B's value (independent deploys, per-persona perf isolation) is real at scale but premature at our size. Option A keeps the architectural intent (persona-shaping is its own layer) without paying the operational price.

The plan's "lift-out trigger" criteria below mean Option B remains accessible without a rewrite — that converts the choice from "now-or-never" to "now-or-later."

## Lift-Out Trigger Criteria

`interfaces/<persona>/` is lifted into a separately deployed service when **any** of the following becomes true:

1. **Release cadence conflict.** A persona's release is regularly blocked by another persona's pending changes for two consecutive release windows.
2. **Independent runtime requirement.** A persona needs a different runtime (e.g., coach needs Node + Edge for sub-50ms TTFB at the edge) that can't be served from the shared FastAPI process.
3. **Tenant scale.** A specific persona's traffic shape (e.g., parent checkout bursts during enrollment season) creates contention with other personas in the shared process that horizontal scaling can't resolve.
4. **Team scale.** Three or more independent teams own the personas and the shared deploy becomes a coordination tax.

Until one of these criteria fires, the layer stays inside the monolith.

## Consequences

**Becomes easier:**
- One deploy, one set of secrets, one CI pipeline, one observability surface.
- Persona-shaping is co-located with domain use cases. Refactors are trivial.

**Becomes harder:**
- Persona deploys are coupled. A misbehaving admin handler can degrade coach latency. Mitigated by SLO-based alerting and edge-routed rollback.
- The "BFF" name will mislead readers who expect a separate deploy. Documentation in `docs/adr/` (this file) and `backend/v2/interfaces/README.md` calls this out.

**To revisit:**
- Any lift-out trigger above is a forcing function for a new ADR superseding this one.

## Action Items

1. [x] Reject three-deployed-BFF, GraphQL, and one-generic-API options.
2. [ ] Build `backend/v2/interfaces/<persona>/` per persona, persona-first directory layout (P0-11, then per wave).
3. [ ] Add a `backend/v2/interfaces/README.md` explaining the layer and the lift-out criteria.
4. [ ] Track lift-out trigger conditions in retros; revisit ADR if any fire.
