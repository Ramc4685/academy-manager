# Tests: stop two tests failing every time the month rolls over

PR: #1036

## What changed

- On 1 October 2026, `main` went red. No code had changed: two tests assumed "this month" is September 2026.
- `test_parent_home_degrades_per_child_when_one_schedule_leg_raises` ran on the wall clock, but its attendance seed is pinned to September. It now uses the same fixed `_HOME_NOW` (15 Sep 2026) as its sibling tests.
- The e2e test "a clean month says so, in one line" expects "Sep 2026 is ready to close", but the page's headline names the browser's current month. The test now pins the browser clock to 15 Sep 2026 with `page.clock.setFixedTime`.

## Deploy notes

- None. Test-only change.

## Risk / rollback

- None for the app. Rollback: revert the PR (main goes red again).
