# Parent skill updates

## Current State

Status: active

## Problem

Stream 4: parent progress page needs recent skill updates and practice video resources without exposing teaching-plan internals

## Changed Files

- None recorded yet.

## Log

- 2026-06-13T11:42:36 main/NA: Task ledger created.
- 2026-06-13T11:44:25 main/working: Started Stream 4 in parent-skill-updates worktree; reading required docs and existing parent progress code before tests.
- 2026-06-13T11:53:41 main/working: Implemented Stream 4 backend routes/use case and parent progress UI. Backend responses allow-list parent fields only; practice resources filter lesson-card links to YOUTUBE links.
- 2026-06-13T11:59:19 main/working: Spec review fix: practice resources must use all current in-progress skill rows, not the limited recent-update window. Starting with failing backend route coverage.
- 2026-06-13T12:02:28 main/working: Fixed spec review issue: practice resources now use current in-progress skill rows instead of the recent-updates window.
## Verification

- No verification recorded yet.
- 2026-06-13T11:48:44: RED then GREEN application slice: backend/.venv pytest v2/tests/contexts/student_progress/test_recent_skill_updates.py -q now passes (1 passed). Initial RED was missing get_recent_skill_updates module.
- 2026-06-13T11:50:53: Backend interface RED then GREEN: backend/.venv pytest v2/tests/interface/test_parent_progress_routes.py -q -k 'parent_skill_updates or parent_practice_resources' now passes (3 passed). Initial RED was 404 Not Found for missing endpoints.
- 2026-06-13T11:53:42: Focused verification passed: backend/.venv pytest v2/tests/contexts/student_progress/test_recent_skill_updates.py v2/tests/interface/test_parent_progress_routes.py -q (14 passed); backend/.venv ruff format --check v2; backend/.venv ruff check v2; frontend pnpm typecheck; frontend pnpm lint. Manual coach-to-parent browser flow not run in this turn.
- 2026-06-13T12:02:29: Spec fix verification: RED route test outside_recent_window failed with empty resources under old recent-window implementation; RED application test failed on missing GetInProgressSkills. GREEN: backend/.venv pytest v2/tests/contexts/student_progress/test_recent_skill_updates.py v2/tests/interface/test_parent_progress_routes.py -q (16 passed); backend/.venv ruff format --check v2; backend/.venv ruff check v2. Frontend checks skipped because no frontend files changed in this fix.
## Reusable Lessons

- None recorded yet.
