# backend/v2 — Clean-Architecture-Lite FastAPI

The v2 codebase implements the architecture frozen in [docs/adr/](../../docs/adr/) and [the migration plan](../../../.claude/plans/write-a-detailed-plan-curried-trinket.md).

This is the production backend runtime. Fly deploys `backend.v2.main:app`, and
all HTTP routes are mounted under `/api/v2/*`.

## Layout

```
backend/v2/
├── contexts/           # bounded contexts: identity, enrollment, coaching, billing, etc.
├── interfaces/         # persona BFF routes: admin, coach, parent, platform
├── shared/
│   ├── auth/           # Firebase token verification, claims, tenancy middleware
│   ├── config/         # pydantic-settings
│   ├── events/         # outbox + dispatcher
│   ├── http/           # error handlers, middleware
│   ├── idempotency/    # @idempotent decorator + Mongo store
│   ├── observability/  # OpenTelemetry + structured logs
│   └── tenancy/        # tenant resolution and tenant-scoped repository helpers
├── migrations/         # idempotent boot migrations and Mongo indexes/validators
├── scripts/            # operator CLIs (e.g., replay_event.py)
├── tests/
│   ├── unit/           # pure domain
│   ├── application/    # use cases with port fakes
│   ├── contract/       # mongo + stripe via testcontainers
│   ├── interface/      # BFF route tests
│   └── structural/     # layer-conformance + event-rules checks
└── main.py             # composition root
```

## Layer rules (enforced by import-linter)

```
interfaces ─────► application ─────► domain
                       ▲
                       │
                  infrastructure
```

See [ADR-0005](../../docs/adr/0005-clean-architecture-lite-monolith.md) for the six layer rules.

## How to add a new context

1. Create `contexts/<name>/{domain,application,infrastructure}/` with `__init__.py` in each.
2. Add the context to `docs/data-ownership.md`.
3. Add domain models in `domain/models.py`, domain events in `domain/events.py`, domain errors in `domain/errors.py`.
4. Add use cases in `application/use_cases/`, ports in `application/ports.py`.
5. Implement infrastructure adapters extending `shared/tenancy/TenantScopedRepository`.
6. Add a migration for indexes in `migrations/`.
7. Add a tenant-isolation test per repository.
8. Wire the context into the composition root in `main.py`.

The Identity context built in W1A-02 is the canonical example to copy from.

## How to add a BFF route

1. Decide the persona — `interfaces/{coach,parent,admin}/`.
2. Check the [security matrix](../../docs/security-matrix.md) — the persona × action cell must be Yes (or Conditional) before you write the route.
3. Create the route file. The router uses the persona-prefix path (`/api/v2/<persona>/<resource>`).
4. The route calls **one or more application use cases** — never a repository, never Mongo directly.
5. Return a view DTO from `interfaces/<persona>/views.py` (persona-shaped).
6. Add a negative test asserting wrong-persona returns 404.

## Running

The v2 code uses absolute imports rooted at `backend.v2.*`, so the
repo root must be on `PYTHONPATH`. Run from the repo root, not from
`backend/`:

```bash
# From repo root (recommended):
PYTHONPATH=. uvicorn backend.v2.main:app --reload --port 8001

# Tests:
PYTHONPATH=. pytest backend/v2/tests
PYTHONPATH=. lint-imports --config backend/pyproject.toml
```

If you must run from `backend/`, set `PYTHONPATH=..`:

```bash
cd backend
PYTHONPATH=.. uvicorn backend.v2.main:app --reload --port 8001
PYTHONPATH=.. pytest v2/tests
PYTHONPATH=.. lint-imports --config pyproject.toml
```

CI uses `PYTHONPATH=${{ github.workspace }}` on every step. See
`.github/workflows/production.yml`.

The v2 app mounts under `/api/v2/*`. Historical `/api/*` legacy routes are not
mounted by `backend.v2.main:app`.

## CI

See `.github/workflows/production.yml`:

- `ruff` (lint)
- `mypy --config-file backend/pyproject.toml v2` (advisory in the backend lint job)
- `import-linter` (layer rules + tenancy)
- `pytest v2/tests` with ≥70% coverage on `v2/shared`
