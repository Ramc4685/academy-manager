# Architecture Rules

`academy-manager` is a strangler migration, not a rewrite.

Legacy FastAPI + CRA stays working while v2 capabilities move one workflow at a time behind BFF, DDD boundaries, and edge routing.

---

## Required References

Read before structural decisions:

1. `README.md`
2. `DEPLOYMENT.md`
3. `test_result.md`
4. The relevant active ledger under `docs/test-results/active/`, if one exists
5. `docs/tickets/README.md`, when present on the branch
6. The active phase or wave ticket sheet, when present

Architecture docs and accepted ADRs override this file.

---

## Current Layout

```txt
backend/
  server.py                 FastAPI legacy composition root
  routers/                  Legacy /api/* routers
  services/                 Legacy shared services
  tests/                    Backend pytest suites

frontend/
  app/                      Next.js App Router route groups
  lib/api/                  Typed BFF clients
  lib/pwa/                  PWA and offline plumbing

docs/
  ci-cd.md                  Deployment/CI documentation
  agent/                    Agent guidance

test_result.md              Main/testing agent feedback index
docs/test-results/          Task-scoped testing ledgers
```

v2 layout, when present:

```txt
backend/v2/
  contexts/                 DDD bounded contexts
  interfaces/               Persona BFF routes
  shared/                   Cross-cutting auth, tenancy, events, idempotency
  migrations/               v2 Mongo index/migration scripts
  tests/                    v2 unit/application/contract/interface tests

edge/
  router.ts                 Edge route switching prototype
```

---

## Layer Rules For v2

| Layer | Location | Responsibility |
| --- | --- | --- |
| Interface / BFF | `backend/v2/interfaces/<persona>/` | HTTP routes, auth dependencies, persona-shaped DTOs |
| Application | `backend/v2/contexts/*/application/` | Use cases and workflow orchestration |
| Domain | `backend/v2/contexts/*/domain/` | Business rules, entities, value objects, domain events/errors |
| Infrastructure | `backend/v2/contexts/*/infrastructure/` | Mongo repositories and external adapters |
| Shared | `backend/v2/shared/` | Cross-cutting auth, tenancy, idempotency, events, observability |

Rules:

- BFF calls application use cases, not Mongo directly.
- Application code depends on ports/protocols, not infrastructure details.
- Domain must not import infrastructure, FastAPI, Firebase, Stripe, or Mongo.
- Infrastructure may implement ports and talk to Mongo/external providers.
- Frontend must not own business truth.

---

## BFF Rules

BFF APIs are audience-shaped.

Current personas:

- Admin
- Coach
- Parent

Examples:

```txt
GET  /api/v2/coach/today
POST /api/v2/coach/attendance
```

Do not create generic table CRUD for every collection. Create workflow endpoints that match the persona's job.

Wrong-persona access for v2 persona routes should not leak data existence. Follow the active security matrix when present.

---

## DDD Context Rules

Initial v2 contexts:

- `identity`: users, roles, auth claims
- `enrollment`: sessions, students, enrollments, roster, capacity, waitlist
- `coaching`: attendance, lesson plans, progress notes, coach workflow queries
- `billing`: payments, subscriptions, Stripe, refunds, webhooks

Do not create empty contexts just to match a diagram. Add a context when a ticket or real workflow needs it.

---

## Migration Rules

- Legacy `/api/*` is production behavior.
- v2 `/api/v2/*` is introduced workflow by workflow.
- Keep legacy and v2 behavior separate.
- A workflow should not call both legacy and v2 for the same user journey once cut over.
- Use feature flags or edge routing for cutover and rollback.
- Do not mark migration phases done until exit gates are verified.
