# lib/api

The base API client + per-persona typed wrappers.

## Files

- `client.ts` — `apiFetch<T>` with auth header injection, in-flight dedup, structured `ApiError`.
- `generated/v2.d.ts` — `openapi-typescript` output from the FastAPI v2 OpenAPI schema. **Committed**; CI fails if a regeneration produces a diff.
- `admin.ts`, `coach.ts`, `parent.ts` — thin typed wrappers (land per wave).

## Regenerating types

The FastAPI app must be running locally:

```bash
# Terminal 1
cd backend
V2_ENABLED=1 uvicorn server:app --reload --port 8001

# Terminal 2
cd frontend
pnpm generate:api
```

Commit the resulting `generated/v2.d.ts`. The PR diff is your contract review.

## CI drift check

`.github/workflows/v2-frontend.yml` regenerates types against the build-time
OpenAPI snapshot and `diff`s against the committed file. Mismatch → CI fails.
This catches the common mistake of changing a route without regenerating the
client.
