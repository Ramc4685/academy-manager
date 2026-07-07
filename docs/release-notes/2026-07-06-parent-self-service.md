# parent-self-service

PR: #TBD

## What changed
Parents can now self-serve from the portal: absence notices, makeup requests
(admin-reviewed), trial-class requests, and enrollment self-cancel with
policy-driven fees. The parent Requests page (`/parent/requests`) exposes
Absences / Makeups / Trials tabs; each submission form shows the same list of
the parent's own past requests with a status chip (pending/approved/denied/
expired/converted). Self-cancel lives on the children page — parents open
"Cancel enrollment…" on an active enrollment, see a preview (fee amount and
effective timing, computed from academy policy) before confirming, and get an
explicit success/blocked outcome.

Admins get review queues (`/admin/requests`) for makeups and trials, a policy
settings page (`/admin/settings/self-service`) to configure notice windows and
cancellation fees, and a cancellations audit list. Coach rosters flag expected
absences and one-time makeup/trial attendees so coaches see who to expect
without cross-referencing the office.

## Deploy notes
Migration `0145_parent_self_service` runs automatically on boot
(`run_pending_migrations`) — creates indexes for 5 new collections
(`parent_self_service_policies`, `absence_notices`, `makeup_requests`,
`trial_requests`, `occurrence_roster_entries`). No new env vars. New daily
scheduler job `expire_makeup_requests` (02:30).

## Risk / rollback
Additive feature: new collections/routes only; no changes to existing billing
flows except an optional cancellation-fee invoice line added via the existing
`AddInvoiceLine` path on self-cancel. Roll back by reverting the deploy; the
migration is index-only (non-destructive), safe to leave in place.

## Verification
- Backend: `pytest v2/tests -q` — 2271 passed, 2 pre-existing failures
  unrelated to this feature (an audit inventory-manifest test not yet updated
  for the new `/admin/requests`, `/admin/settings/self-service`, and
  `/parent/requests` frontend routes; see the test ledger for detail).
- Backend: `ruff format --check v2`, `ruff check v2` — clean.
- Backend: `lint-imports --config backend/pyproject.toml` (run from repo
  root) — 4 contracts kept, 0 broken.
- Frontend: `pnpm typecheck`, `pnpm lint` — clean (lint has 5 pre-existing
  warnings unrelated to this feature).
- Frontend unit: node-test suite (32/32) and vitest suite (22/22, including
  `lib/parent-requests.test.ts`) — all passing.
- E2E: new `frontend/e2e/specs/parent-self-service.spec.ts` — 5 scenarios
  covering absence notices (list, on-time submit, late-notice warning),
  makeup request submission (pending chip), and self-cancel (fee/timing
  preview before confirm, then confirmation) — 10/10 passing across the
  chromium-mobile and webkit-mobile projects.
