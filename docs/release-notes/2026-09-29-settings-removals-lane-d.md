# Remove what's broken or duplicated in Settings (Settings overhaul Phase 2 PR 7)

PR: #1004

## What changed

- **Data tab removed** (`Settings -> Data`, `data-panel.tsx`). All three of its download buttons 404'd; the Reports pages already export the same CSVs. `?panel=data` now redirects an owner to `/admin/reports` and a non-owner (who cannot reach Reports) to the default Settings panel instead.
- **Roles tab removed** (`Settings -> Roles`, `roles-panel.tsx`). It duplicated the Staff page's role editor (`/admin/users`). `?panel=roles` now redirects there.
- **Two dead backend routes retired:** `GET`/`PATCH /admin/academy/fees` and `PUT /admin/billing/settings/invoice-schedule`. Neither has a caller left anywhere in the frontend, scripts or tests — the Billing rules panel (`POST /admin/billing/rules`) already reuses the same use cases underneath. `GET /admin/billing/settings/invoice-schedule` stays; the family billing tab still reads it. Both retired routes are dropped from `OWNER_ONLY_ROUTE_PATHS` and now answer 404.
  - **Not removed, despite the spec:** `GET /admin/academy/gateway/stripe/callback`. Verification found this is the *live* Stripe Connect OAuth redirect target (wired via `STRIPE_CONNECT_CALLBACK_URI`/`complete_stripe_connect_use_case`, part of the Stripe Connect lifecycle shipped in PR #969) — not old/dead code. Removing it would break Stripe Connect onboarding in production. See `follow_ups`.
- **New-academy bootstrap no longer writes four unread collections:** `academy_settings`, `billing_policies`, `academy_roles`, `academy_feature_flags`. Verified with a repo-wide grep that nothing under `backend/v2` (outside the bootstrap store, migrations and tests) reads any of the four. `MongoTenantBootstrapStore.ensure_*` methods for them, and the matching `TenantBootstrapStore` protocol methods, are removed; `BootstrapAcademy._ensure_defaults` no longer calls them. No existing collections or documents are dropped — this only stops *new* writes on future bootstraps.
- Also removed as now-dead: the `ComingNextCard` component (only used by the two removed panels), and the frontend's unused `getAdminFees`/`updateAdminFees`/`setInvoiceSchedule` fetchers and their now-orphaned types.
- Redirects for every other retired Settings key (`?panel=fees` -> Billing rules) are unchanged.

## Deploy notes

- No migration. No BLNO behaviour change: the Data and Roles tabs' functionality already existed elsewhere (Reports, Staff), and the four bootstrap collections were never read, so nothing reads a different value at runtime.
- New academies bootstrapped after this deploys simply will not get `academy_settings`/`billing_policies`/`academy_roles`/`academy_feature_flags` documents. Existing academies (including BLNO) keep whatever those collections already hold; nothing deletes them.

## Risk / rollback

- Main risk: if something outside `backend/v2` (a script, an external integration) reads the four bootstrap collections or calls the two retired routes without showing up in this repo's grep, it would now see stale/absent data or a 404. The grep covered `backend`, `frontend`, `scripts`, tests and e2e specs.
- Rollback: revert this PR. No data was dropped, so nothing needs restoring; a re-bootstrap of an academy created in the gap would simply start writing the four collections again once the revert lands.
