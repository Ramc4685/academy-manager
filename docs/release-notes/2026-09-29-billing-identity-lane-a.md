# Billing identity: currency locked to USD, invoice prefix in platform tenant page, timezone required at bootstrap

PR: #TBD

## What changed

- Currency is locked to USD (owner decision). The academy Settings panel's Currency field is now a read-only "USD" field with hint "Set by CourtMastr. All charges are in US dollars." — the 14-option select is gone and the panel no longer sends a chosen currency on save.
- The admin academy update endpoint (`PATCH /api/v2/admin/academy`) rejects any `currency` other than `"USD"` with a 422; omitting the field or sending `"USD"` is a no-op. No stored data is rewritten.
- The Settings panel's Identity card already read the invoice prefix read-only (Phase 1 PR 2); unchanged here.
- The platform tenant detail page (`/platform/tenants/{academyId}`) gets a new "Billing identity" card: shows the invoice prefix and currency (USD), and lets a platform admin change the prefix via the existing `/platform/academies/{id}/billing-identity` endpoint (PR #987). Once that endpoint reports the prefix locked (after the first numbered invoice), the card goes read-only with that reason. The endpoint's own error messages (format, uniqueness, locked) are surfaced in the edit dialog.
- The platform "Bootstrap academy" dialog now requires a timezone (a select, matching the admin Settings timezone picker) instead of silently defaulting to `"UTC"` when left blank. The backend bootstrap route (`POST /platform/academies/bootstrap`) already required a non-empty `timezone`; this closes the frontend gap that let it default silently.

## Deploy notes

- No migration. No env or secret change.
- BLNO and every other existing academy is unaffected: currency was already `"USD"` for every academy in practice, and the invoice prefix and billing-identity endpoint already existed (PR #987 / Phase 1 PR 2).

## Risk / rollback

- Low. The currency change only removes UI/API surface for a value nothing used (every academy is USD today); the 422 only fires if a caller explicitly sends a non-USD currency, which the frontend never did after this change and never encouraged before it either.
- The bootstrap timezone change is stricter validation on a platform-admin-only, low-volume route; a revert is a single-file frontend change.
- Revert by reverting this PR; no data migration to unwind.
