# fix-schedule-edit-orphans-test-monday

PR: #873

## What changed

- Test-only. The regression suite for #783 (`test_session_edit_occurrence_orphans.py`) failed every Monday after 09:00 Central, blocking every branch's pre-push gate and CI on that day (#869). Its fixture schedules a Monday 09:00 class starting today; once that class has started, today's occurrence is history, and the schedule-edit cascade leaves history alone by design. The suite was asserting that the row would be re-keyed or cancelled.
- The suite now asserts re-key and soft-cancel behaviour only on occurrences that are still in the future, which is the set the cascade acts on. The cascade itself was checked and is correct: an admin moving a class off Monday on a Monday afternoon keeps that morning's class, with its attendance and coach pay, intact. No production code changed.

## Deploy notes

Nothing to deploy or apply. No migrations, no env vars.

## Risk / rollback

None to production. To roll back, revert this PR's merge commit; the suite would go back to failing on Mondays.
