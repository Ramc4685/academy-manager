# lib/api

The base API client + per-persona typed wrappers.

## Files

- `client.ts` — `apiFetch<T>` with auth header injection, in-flight dedup, structured `ApiError`.
- `admin.ts`, `admin-teaching.ts`, `coach.ts`, `curriculum.ts`, `me.ts`,
  `parent.ts`, `registration.ts` — thin typed wrappers around current v2 BFF
  endpoints.
- `v2/` — focused typed modules for newer contracts such as memberships,
  payouts, payroll, sessions, and students.
- `generated/` — reserved for generated OpenAPI output. It currently contains
  only `.gitkeep`; no OpenAPI snapshot or generated `v2.d.ts` is committed.

## Regenerating types

The FastAPI app must be running locally:

```bash
# Terminal 1
cd backend
PYTHONPATH=.. uvicorn backend.v2.main:app --reload --port 8001

# Terminal 2
cd frontend
pnpm generate:api
```

When generated types are reintroduced, commit the resulting
`generated/v2.d.ts` and review the PR diff as the API contract change.

## CI drift check

`.github/workflows/production.yml` runs an OpenAPI drift check only when
`frontend/lib/api/openapi.snapshot.json` exists. Because the snapshot is not
currently committed, CI prints "No openapi.snapshot.json yet. Skipping drift
check." and relies on the hand-written typed client modules plus their focused
tests.
