---
name: v2-persona-slice
description: This skill should be used when working in academy-manager and the user asks to add or change v2 backend routes, BFF APIs, DDD contexts, persona workflows, tenant isolation, SaaS paths, admin/coach/parent/platform interfaces, or migration-related backend/frontend slices.
version: 0.1.0
---

# V2 Persona Slice

Use this skill to keep academy-manager v2 changes aligned with its BFF and DDD architecture.

## Before Editing

1. Read the relevant project guidance:

   ```bash
   sed -n '1,220p' AGENTS.md
   sed -n '1,220p' docs/agent/architecture-rules.md
   sed -n '1,220p' docs/agent/backend-api-rules.md
   sed -n '1,220p' docs/agent/frontend-rules.md
   ```

2. Identify the persona and boundary:

   - Admin BFF routes: `backend/v2/interfaces/admin/`
   - Coach BFF routes: `backend/v2/interfaces/coach/`
   - Parent BFF routes: `backend/v2/interfaces/parent/`
   - Platform routes: `backend/v2/interfaces/platform/`
   - Application use cases: `backend/v2/contexts/<context>/application/`
   - Domain rules: `backend/v2/contexts/<context>/domain/`
   - Mongo/Firebase/Stripe/Resend adapters: `backend/v2/contexts/<context>/infrastructure/`

3. Inspect matching tests before adding new behavior:

   ```bash
   find backend/v2/tests -path '*interface*' -o -path '*contexts*' | sort
   ```

## Implementation Rules

- Keep legacy `/api/*` stable. Do not patch legacy routes for SaaS readiness.
- Add SaaS workflows only in `backend/v2/`.
- Keep BFF routes persona-shaped; avoid generic CRUD endpoints when the user workflow has a clear persona.
- Let application use cases orchestrate workflows.
- Keep business rules in domain modules.
- Keep direct external service calls in infrastructure modules.
- Do not import infrastructure or domain directly from interfaces unless an existing explicit exception exists.
- Resolve tenant identity explicitly from subdomain, custom domain, or approved internal header.
- Never infer tenant from user alone.
- Avoid `default_academy_id` in SaaS request paths.
- Add tenant isolation tests for every tenant-owned read/write.
- Keep frontend pages presentation-focused; backend owns business truth.

## Verification

Use focused tests for touched boundaries first:

```bash
cd backend
source .venv/bin/activate
pytest v2/tests/interface/test_relevant_routes.py -q
pytest v2/tests/contexts/relevant_context -q
ruff check v2
ruff format --check v2
```

For frontend callers:

```bash
cd frontend
pnpm typecheck
pnpm lint
```

For broad backend boundary risk:

```bash
cd backend
source .venv/bin/activate
lint-imports --config pyproject.toml
pytest v2/tests -q
```

Record all results in the relevant active test ledger before final response.
