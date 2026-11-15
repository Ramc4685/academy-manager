# Drift: frontend/lib/api

README: `frontend/lib/api/README.md`. Code: `frontend/lib/api/` (HEAD plus the working tree as of 2026-11-14).

Counts: stale-not-built 2, missing 0, contract 1, undocumented 7, wording 1. Total 11 (undocumented bullets are grouped; each group lists its files).

## Divergences

- [stale-not-built] README `frontend/lib/api/README.md:13-14` says `generated/` holds only `.gitkeep` and that no OpenAPI snapshot or generated `v2.d.ts` is committed. Code: `frontend/lib/api/generated/v2.d.ts:1-3` (auto-generated header) and `frontend/lib/api/openapi.snapshot.json:1` both exist and are tracked in HEAD. Commit `63f0c0df2` added the CI check.
- [stale-not-built] README `frontend/lib/api/README.md:33-39` says CI prints "No openapi.snapshot.json yet. Skipping drift check." and relies on hand-written clients. Code: `.github/workflows/production.yml:312-320` ("OpenAPI drift check") runs unconditionally in the `frontend-static` job, with no step-level `if:` and no skip message. It diffs `openapi-typescript` output against `generated/v2.d.ts` and fails on mismatch.
- [contract] README `frontend/lib/api/README.md:18-28` says `pnpm generate:api` regenerates types from the running FastAPI app on port 8001. Code: `frontend/package.json:16` runs `openapi-typescript lib/api/openapi.snapshot.json -o lib/api/generated/v2.d.ts`, which reads the committed snapshot and never contacts the app. The snapshot is refreshed by `UPDATE_OPENAPI_SNAPSHOT=1 pytest backend/v2/tests/structural/test_openapi_snapshot.py` (`backend/v2/tests/structural/test_openapi_snapshot.py:1-12`), and that step is absent from the README.
- [undocumented] `client.ts:249` `apiFetchBlob`, an authenticated binary-download helper (xlsx/pdf) that skips JSON parsing. The README lists only `apiFetch<T>` (`README.md:7`).
- [undocumented] `client.ts:87` `reportApiFailure` and `client.ts:74` `apiRouteTemplate`. Sentry capture of 5xx and transport failures, with network failures collapsed into one fingerprint (`client.ts:103-119`).
- [undocumented] `client.ts:15` `X-CourtMastr-Identity` BFF header and `client.ts:188-190` / `client.ts:265-267` `X-Academy-Id` injection from localStorage (`client.ts:25-43`). The README mentions auth header injection only (`README.md:7`).
- [undocumented] `client.ts:172` default 20 s abort timeout (`timeoutMs = 20_000`) on `apiFetch`.
- [undocumented] Admin modules not named in the README "Files" list (`README.md:8-9`): `admin-account-deletions.ts:4`, `admin-ai-import.ts:16`, `admin-crm-pipeline.ts:15`, `admin-families.ts:9`, `admin-family-contacts.ts:14`, `admin-family-crm.ts:13`, `admin-family-import.ts:17`, `admin-people-duplicates.ts:13`.
- [undocumented] Other top-level modules not named in the README: `auth-bridge-cookie.ts:3`, `auth-token.ts:1`, `billing-contract.ts:64`, `coach-paths.ts:1`, `magic-link.ts:3`, `parent-home.ts:12`, `payment-error.ts:12`, `platform.ts:12`, `proxy-headers.ts:5`, `proxy-origin.ts:4`, `student.ts:14`, `unsubscribe.ts:3`.
- [undocumented] `v2/` modules not named in the README (`README.md:10-12` names only memberships, payouts, payroll, sessions, students): `v2/announcements.ts:10`, `v2/departure-policy.ts:12`, `v2/messages.ts:10`, `v2/owner.ts:12`, `v2/pricing.ts:12`, `v2/session-types.ts:10`.
- [wording] README `frontend/lib/api/README.md:30-31` says "When generated types are reintroduced, commit the resulting `generated/v2.d.ts`". Code: `generated/v2.d.ts` is already committed and CI-checked (`.github/workflows/production.yml:317-318`), so the conditional framing is outdated.
