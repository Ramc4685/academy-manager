# Hold start notification and parent visibility

PR: #759

## What changed

- Fixes #740 — `HoldEnrollment` now takes the existing `HoldNotifier` and fires a new `hold_started` notice the day a hold is placed, sent through the same claim-then-send path (notice key `hold-start:{hold_seq}`) already used for reclaim/reminder emails. The send is best-effort: a mail failure never rolls back the committed hold. `composition/enrollment_holds.py` wires the already-built `hold_notifier` into the single `HoldEnrollment` construction site.
- Fixes #740 — the parent read model no longer hides held enrollments. `list_enrollments_for_parent` widens its status filter to include `held` and returns `hold_return_on`; `list_children_for_parent` adds a separate `held_session_count`. The parent Children page renders an "On hold until \<date\>" chip plus a note explaining the empty upcoming-sessions list. Self-cancel stays hidden for held rows (the API already rejects it), and the upcoming-schedule query is unchanged — a held child correctly has no sessions.

## Deploy notes

- No migration and no new environment variables.
- Frontend and backend ship together; the parent Children page depends on the widened `list_enrollments_for_parent`/`list_children_for_parent` response shape.

## Risk / rollback

- Additive: existing hold/return flows, billing sync, and non-held enrollment reads are unchanged. The new notification is best-effort and cannot block or reverse a hold.
- Rollback: revert the PR. No data migration is needed to roll back — held rows simply disappear from the parent view again.
