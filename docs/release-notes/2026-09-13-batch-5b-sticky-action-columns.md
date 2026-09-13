# Sticky action columns in admin approval queues

PR: #0

## What changed
- Fixes #747 — the Approve/Deny/Review action column in the admin approval queues (Makeups, Trials, Pauses, Level-ups, Registrations, now consolidated under `/admin/inbox` per #776) was not sticky and could scroll off-screen on wide tables; it now uses the same sticky-action-column pattern already shipped on the session detail page (#716/#717).
- Extracted the sticky-action CSS helpers into a new shared module `frontend/lib/sticky-action-column.ts` and re-exported them from `frontend/lib/format.ts` so existing consumers (RosterPanel, SessionEditing, WaitlistTable) are unaffected.
- Applied `actionHeaderClass`/`actionCellClass` to all 5 tables in `components/admin/requests/request-queues.tsx` (Makeups, Trials, Pauses, Level-ups, Registrations).
- Gave every action-column header real, visible text: Makeups/Trials/Pauses went from `sr-only` to "Actions", Level-ups went from an empty-string column label to "Actions"; Registrations' already-visible "Review" header got the sticky class.

## Deploy notes
No migration detected in the diff. Frontend-only change; no manual env var or manual step needed before merge.

## Risk / rollback
Low risk — purely a CSS/markup change reusing an existing, already-shipped sticky-action pattern; no data or API changes. If it regresses (e.g. layout shift or overlap on some viewport), revert this PR's merge commit.
