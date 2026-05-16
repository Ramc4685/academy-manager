# backend/v2 — Clean-Architecture-Lite FastAPI

The v2 codebase implements the architecture frozen in [docs/adr/](../../docs/adr/) and [the migration plan](../../../.claude/plans/write-a-detailed-plan-curried-trinket.md).

Legacy code under `backend/` (routers, services, models.py) stays running until each workflow's v2 counterpart cuts over via Cloudflare edge routing.

## Layout

```
backend/v2/
├── contexts/           # bounded contexts — empty for now; one is added per wave
├── interfaces/         # BFF — persona first, context second; empty until Wave 1A
├── shared/
│   ├── auth/           # Firebase verify, role guards (Wave 1A wires this up)
│   ├── config/         # pydantic-settings
│   ├── events/         # outbox + dispatcher + dead-letter + audit (P0-13)
│   ├── http/           # error handlers, middleware
│   ├── idempotency/    # @idempotent decorator + Mongo store (P0-14)
│   ├── observability/  # OpenTelemetry + structured logs (P0-15)
│   └── tenancy/        # academy_id ContextVar + TenantScopedRepository (P0-12)
├── migrations/         # idempotent boot migrations (P0-16)
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
`.github/workflows/v2-backend.yml`.

v2 mounts under `/api/v2/*`. Legacy stays on `/api/*`.

## CI

See `.github/workflows/v2-backend.yml`:

- `ruff` (lint)
- `mypy --strict backend/v2`
- `import-linter` (layer rules + tenancy)
- `pytest backend/v2/tests/` with ≥80% coverage on `shared/`
