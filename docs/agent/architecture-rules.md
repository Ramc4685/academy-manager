# Architecture Rules

`academy-manager` is a strangler migration, not a rewrite.

The production app now runs the v2 FastAPI runtime and the Next.js frontend.
Historical migration docs still describe the strangler path, but current work
should treat `backend/v2/` and `frontend/` as the active implementation.

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
  v2/                       Production FastAPI app
  scripts/                  Backend import, audit, seed, and repair scripts
  pyproject.toml            Backend lint, type, pytest, and import-linter config

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

backend/v2/
  contexts/                 DDD bounded contexts
  interfaces/               Persona BFF routes
  shared/                   Cross-cutting auth, tenancy, events, idempotency
  migrations/               v2 Mongo index/migration scripts
  tests/                    v2 unit/application/contract/interface tests

edge/
  router.ts                 Retired edge-routing reference and tests
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

Current v2 contexts:

- `identity`: users, roles, memberships, auth claims, tenant bootstrap
- `enrollment`: sessions, students, enrollments, roster, capacity, waitlist, pauses
- `coaching`: attendance, lesson plans, progress notes, skill notes, coach workflows
- `billing`: invoices, payments, subscriptions, Stripe, refunds, webhooks, tuition discounts
- `finance`: payroll, payout periods, reporting snapshots
- `communications`: campaigns, coach digests, delivery logs
- `curriculum`: pathways, levels, skills, criteria, lesson cards
- `student_progress`: placements, skill status, tests, level-up, certificates
- `onboarding`: applications, waiver templates, signatures
- `platform`: tenant lifecycle, platform billing, governance, audit

Do not create empty contexts just to match a diagram. Add a context when a ticket or real workflow needs it.

---

## Migration Rules

- Production HTTP APIs are under `/api/v2/*`.
- Do not add new frontend calls to legacy `/api/*` routes.
- Keep legacy compatibility adapters isolated when they are still needed for
  single-academy launch behavior; do not use them for SaaS request paths.
- SaaS work must use explicit tenant resolution and request-scoped tenant context.
- Do not mark migration or launch phases done until exit gates are verified.
