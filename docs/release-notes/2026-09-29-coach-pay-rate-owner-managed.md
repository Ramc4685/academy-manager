# Coach pay rates: admin sees a read-only note, not an error (Settings overhaul Phase 2 PR 8)

PR: #TBD

## What changed

- On the Staff page for a coach (`/admin/users/[userId]`), a plain admin (no `owner` role) used to have the pay-rate panel silently call `GET /api/v2/admin/coaches/{coach_id}/pay-rates`, which is owner-only (`require_owner`, 404 for a plain admin per `owner_gate.py`) and always failed for them.
- The panel now checks the caller's owner scope before it ever calls that route. A plain admin sees a small read-only card — "Only the academy owner can view or change coach pay rates." — instead of the failed fetch. Owners see the exact same panel as before: rate history, the set-pay-rate form and the rate-gap repair flow.
- Pay rates stay owner-only money (per `owner_gate.py`'s money-governance rules); this only stops the error, it does not open the data to admins.
- Added `frontend/app/no-duplicate-route-urls.test.ts`, a cheap structural check that walks `app/` and fails if two `page.tsx`/`route.ts` files (e.g. across different route groups) resolve to the same URL — the frontend analogue of the existing `backend/v2/tests/structural/test_no_duplicate_routes.py` (the #967 Pathway route-collision class of bug). No collisions found in the current tree.

## Deploy notes

- No migration. No API contract change — the route was already owner-only; this is a frontend-only fix to stop calling it for non-owners.
- BLNO's owners see no change. Admins without `owner` on a coach's Staff page no longer see the pay-rate panel error out.

## Risk / rollback

- Low risk: the fix narrows a `useQuery`'s `enabled` flag and adds an early return in one client component. No new data exposure — the panel was never able to show real data to a non-owner anyway (the fetch always 404'd), it now just fails cleanly.
- Rollback: revert this PR. No data or migration to undo.
