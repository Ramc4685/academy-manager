# Batch 3b: withdraw dedupe notice

PR: #0

## What changed

- Fixes #772 — Admin Drop was mailing the family two emails with two different wordings. PR #767 (#743) added a family-facing `enrollment_dropped` notice to `WithdrawEnrollment` but left `withdrawn` in `_PARENT_STATUS_CHANGES`, so the roster "withdrawn" alert also went to the parent. `withdrawn` is now removed from `_PARENT_STATUS_CHANGES`: the roster alert stays the coach/staff copy, and `enrollment_dropped` is the single family-facing notice. `StopAllClasses` composes the same `WithdrawEnrollment` use case per row, so it inherits the fix automatically. All three paths (single withdraw, stop-all-classes, and the roster alert adapter itself) are now pinned with tests against the real adapter so this can't regress silently.

## Deploy notes

- No migrations. No config or environment changes. Backend-only change (`backend/v2/composition/roster_notifications.py`); no frontend changes.

## Risk / rollback

- Low risk: the change removes one entry from a frozenset that gated an already-duplicate parent notification path; behavior for coach/staff alerts and every other status transition (`cancelled`, `paused`, `resumed`, `session_cancelled`) is untouched. Covered by new/updated tests in `test_withdraw_single_path.py`, `test_stop_all_classes.py`, and `test_roster_alert_adapter.py`. Rollback: revert this PR, which restores the double-send bug — no data migration involved.
