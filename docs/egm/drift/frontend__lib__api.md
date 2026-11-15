## frontend/lib/api/README.md

- [stale-not-built] README lines 12-14 ("`generated/` ... currently contains only `.gitkeep`; no OpenAPI snapshot or generated `v2.d.ts` is committed"): `frontend/lib/api/generated/v2.d.ts` (about 1 MB) and `frontend/lib/api/openapi.snapshot.json` (about 1.4 MB) are both tracked in git. The worktree also modifies both (admin API additions). There is no `.gitkeep` in `generated/`.
- [stale-not-built] README lines 28-29 ("When generated types are reintroduced, commit the resulting `generated/v2.d.ts`"): the types are already committed. The generate script (`frontend/package.json:16`) builds `v2.d.ts` from the snapshot.
- [contract] README lines 18-27 (regeneration needs the FastAPI app running locally, with uvicorn on port 8001): `frontend/package.json:16` has `generate:api` run `openapi-typescript lib/api/openapi.snapshot.json -o lib/api/generated/v2.d.ts`. It reads the snapshot file and does not call a running server. The README's two-terminal flow does not refresh the snapshot, so it would not pick up the new backend routes and schemas. The doc does not say how the snapshot itself is regenerated. A backend structural test keeps it equal to the live API (`.github/workflows/production.yml:313`).
- [contract] README lines 31-36 (CI runs the drift check only if `openapi.snapshot.json` exists, otherwise prints "No openapi.snapshot.json yet. Skipping drift check."): `.github/workflows/production.yml:313-320` always runs `openapi-typescript` on the snapshot and does `diff -q` against `generated/v2.d.ts`. It fails with "lib/api/generated/v2.d.ts is out of date. Run 'pnpm generate:api' and commit the result." There is no skip path. The README is also wrong that CI relies only on hand-written client modules and their tests.
- [undocumented] Uncommitted additions in `frontend/lib/api/admin.ts` (the README only says the file is a "thin typed wrapper"). These are new admin API types that mirror the regenerated snapshot and types:
  - `AdminAttentionKind` gains `"autopay_stuck"` (line 1375).
  - `RefundFailure` and `RefundFailures` types, plus the optional `ConnectReadiness.refund_failures` (about lines 2432-2450).
  - `OpenDispute` and `OpenDisputes` types, plus the optional `ConnectReadiness.disputes`.
  - `ConnectReadiness.payments_blocked_reason`.
  - `ConnectedAccountReadiness.direct_charges_supported`, `fees_collector` and `losses_collector`.
  - `DunningRow.parked_reason` and `DunningRow.parked_since` (about lines 2553-2555).

  The README does not mention these fields or the snapshot as the source of the contract. Most are optional (`?`) in `admin.ts`.
- [undocumented] README lines 7-10 list `admin.ts`, `admin-teaching.ts`, `coach.ts`, `curriculum.ts`, `me.ts`, `parent.ts` and `registration.ts`. Many other modules in `frontend/lib/api/` are not listed:
  - `admin-account-deletions.ts`, `admin-ai-import.ts`, `admin-crm-pipeline.ts`, `admin-families.ts`, `admin-family-contacts.ts`, `admin-family-crm.ts`, `admin-family-import.ts`, `admin-people-duplicates.ts`
  - `billing-contract.ts`, `platform.ts`, `student.ts`, `parent-home.ts`, `magic-link.ts`, `unsubscribe.ts`, `payment-error.ts`
  - `auth-bridge-cookie.ts`, `auth-token.ts`, `coach-paths.ts`
  - `proxy-headers.ts`, `proxy-origin.ts`
- [wording] README line 11 describes `v2/` as covering "memberships, payouts, payroll, sessions, and students". `frontend/lib/api/v2/` also has `announcements.ts`, `departure-policy.ts`, `messages.ts`, `owner.ts`, `pricing.ts` and `session-types.ts`.
