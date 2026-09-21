# batch-10b: deterministic occurrence-orphan tests

PR: #884

## What changed
- Fixes #872 — `backend/v2/tests/contract/test_session_edit_occurrence_orphans.py`
  no longer depends on the wall clock the suite happens to run under.
  `maintain_session_occurrences` and its helpers in
  `backend/v2/composition/admin.py` read `datetime.now(UTC)` live, so on the
  schedule's own weekday, at or after its 09:00 start, today's occurrence
  already counts as started and the #589/#593 "never rewrite a started
  class" rule leaves it alone — which flipped 8 assertions in this file
  depending on the real date/time the suite ran (most recently every
  Monday afternoon).
- The test file now freezes `backend.v2.composition.admin.datetime` to a
  fixed instant (2026-01-05 12:00 UTC, a Monday, 06:00 America/Chicago,
  outside DST) via an autouse fixture, using the same `datetime` subclass
  monkeypatch pattern already used in `test_admin_sessions.py` — no new
  dependency was added. Also added
  `test_schedule_edit_keeps_todays_started_class_but_rekeys_later_weeks`,
  which freezes the clock a second time to 16:00 UTC (10:00 Chicago, after
  the class has started) and pins the CURRENT production behaviour
  explicitly: today's already-started occurrence keeps its status and
  `occurrence_id` untouched, while a later Monday that has not started is
  still re-keyed/cleared like any other future occurrence.
- Test-only change. No production code in `backend/v2/composition/admin.py`
  or elsewhere was modified — the decision was to keep the existing
  #589/#593 behaviour exactly as-is and make the test suite pin it
  deterministically instead.

## Deploy notes
No migration. Test-only change confined to
`backend/v2/tests/contract/test_session_edit_occurrence_orphans.py`; no
manual env var or manual step is needed before merge.

## Risk / rollback
Very low risk: no runtime code changed, only test fixtures and one new
test case. The full contract and structural suites pass locally, and the
target file's outcome was verified deterministic across `TZ=America/Chicago`,
`TZ=UTC`, and `TZ=Australia/Sydney`. Revert this PR to roll back.
