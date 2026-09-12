# Session roster held accounting

PR: #0

## What changed

- Fixes #734 — Held enrollments keep their seat (`SEAT_HOLDING = active + held`) and are counted
  by `SeatBroker`, but three admin display surfaces (class roster capacity, session-list capacity,
  and the Add flow) filled from active rows only. A full class of holds advertised open spots, and
  the resulting Add silently fell through to `claim_longest_held`, dropping the longest-held child.
  These surfaces now count held seats consistently with `SeatBroker`.
- Fixes #735 — The Active/Past roster tabs on the session detail page (added in #712) partitioned
  enrollments purely on `status === "active"`, so `held` and `reclaim_pending` rows — both live,
  still-actionable statuses (`RosterPanel`'s `rosterActionsFor` offers return/transfer/drop on them)
  — landed in the Past tab next to genuinely departed students (cancelled/deleted/withdrawn/dropped).
  Extracted an exported `partitionRoster()` helper in `RosterPanel.tsx` that treats
  active = {active, held, reclaim_pending} and everything else as past, and switched `page.tsx`'s
  roster split to use it.

## Deploy notes

No migrations. No new env vars or manual steps. Pure application-code/display-logic fixes on top of
existing seat and roster data.

## Risk / rollback

Low risk: changes are scoped to read-side capacity counting and roster tab partitioning, plus the
Add flow's seat-availability check. If this regresses, revert this PR — no data migration is
involved so a revert fully restores prior behavior.
