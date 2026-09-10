# admin-roster-shows-held

PR: #717

## What changed

Fixes a live defect (#714): a held student vanished from the admin class roster. `HoldEnrollment` moves an enrollment to `held` (#697), but the admin roster read still filtered on `active`/`paused` only, while the coach roster reads `active`/`held` — so the two personas disagreed about who was in the class. The held row still held a seat, so a class could read as full with nobody visible to explain why, and Return was unreachable because there was no row to act on. This is the #641 dead end reintroduced for the #697 statuses. The read now lists `active`, `paused`, `held` and `reclaim_pending`. Roster rows also gained `parent_name` (one batched `users` query) so the departure dialogs can name who gets emailed. The structural test that pinned the old filter as a literal string was updated in the same commit, as was the interface conftest roster fake that documents itself as mirroring production.

## Deploy notes

No migration, no new env vars, no manual steps. Frontend `AdminEnrollmentView` gained `parent_name: string | null`; `RosterPanel`'s existing ON HOLD chips for `held`/`reclaim_pending` become reachable for the first time.

## Risk / rollback

Visibility only — seat arithmetic is untouched and `test_admin_session_seat_counts_stay_active_only` still asserts `enrolled_count` counts `active` alone. Held and reclaim_pending rows will now appear on rosters where admins previously saw nothing, which is the intended correction. Full backend suite passes (4611). Revert the merge commit if this regresses.
