# fix-uim2-memberships-route

PR: #366

## What changed
Added `GET /me/memberships` (`backend/v2/interfaces/me_routes.py`), backed by a
new `ListMyMembershipsUseCase` that joins the caller's active `academy_memberships`
rows with academy display names/slugs and marks the row matching the caller's
resolved tenant as `is_default`. Swapped the frontend's single-academy stub in
`frontend/lib/api/v2/memberships.ts` for a real call to the new endpoint, so
`TenantSwitcher` now goes live for users with more than one membership instead
of always rendering the single-academy pill. Also fixed a latent concurrency
bug in `apiFetch`'s GET request-dedup logic (`frontend/lib/api/client.ts`):
the original request consumed the shared `Response` body directly, so a
second concurrent identical GET (e.g. React Strict Mode's double-effect in
dev) would race to `.clone()` an already-read stream and throw. This surfaced
only once `TenantProvider` became the first concurrently-invoked `apiFetch`
consumer; the fix reads from `res.clone()` unconditionally so any number of
deduped callers can clone safely.

## Deploy notes
None — no migrations, no new env vars. Purely additive backend route plus a
frontend client swap.

## Risk / rollback
Low risk: the route only returns the caller's own active memberships (no
persona gate beyond authentication), and inactive/removed memberships are
filtered server-side before reaching the switcher. Rollback: revert this PR;
`frontend/lib/api/v2/memberships.ts` falls back to the removed single-academy
stub and the route becomes unused (additive, safe to leave or remove).
Verified: full backend `v2/tests` suite (2590 tests) green, `ruff check`
clean; frontend `pnpm typecheck`/`pnpm lint` clean; full `pnpm e2e` suite
(266 passed, 186 skipped — gated real-auth/local-auth specs) green, including
new/updated coverage for both single- and multi-membership TenantSwitcher
behavior in `admin-shell.spec.ts`.
