# Admin teaching plan visibility

## Current State

Status: active

## Problem

Stream 3: admin session detail needs read-only teaching plan visibility and optional coach engagement stats

## Changed Files

- None recorded yet.

## Log

- 2026-06-13T11:42:36 main/NA: Task ledger created.
- 2026-06-13T11:44:38 main/working: Starting Stream 3 implementation; required docs and active ledger read, inspecting coach/admin/progress paths before writing failing backend tests.
- 2026-06-13T12:00:05 main/working: Implemented Stream 3 backend admin occurrence teaching-plan endpoint, coach engagement stats aggregation/route, admin read-only teaching-plan frontend tab/component, and coaches engagement stats strip. Manual app check blocked by missing frontend Firebase API key.
- 2026-06-13T12:06:31 main/working: Spec review fix: adding RED coverage for admin teaching-plan occurrence.template_session_id before changing route resolution.
- 2026-06-13T12:21:03 main/working: Addressed Stream 3 quality review: filtered engagement stats to recorded outcome statuses, added student_progress engagement index migration, and renamed coach stats UI labels to avoid event-history overclaim.
## Verification

- No verification recorded yet.
- 2026-06-13T11:48:10: RED: source backend/.venv/bin/activate && pytest v2/tests/interface/test_admin_teaching_plan.py v2/tests/interface/test_admin_progress_routes.py::test_coach_engagement_stats_route_returns_counts_for_date_range -q -> expected failures: admin teaching-plan route 404 and admin progress coach-engagement route 404 (2 failed, 2 passed).
- 2026-06-13T11:51:06: GREEN: source backend/.venv/bin/activate && pytest v2/tests/interface/test_admin_teaching_plan.py v2/tests/interface/test_admin_progress_routes.py::test_coach_engagement_stats_route_returns_counts_for_date_range -q -> 4 passed.
- 2026-06-13T11:57:05: Backend interface: source backend/.venv/bin/activate && pytest v2/tests/interface -q -> 400 passed, 1 warning (PytestCollectionWarning for TestAttempt model).
- 2026-06-13T11:59:22: Frontend/backend checks: pnpm install --frozen-lockfile succeeded; pnpm typecheck passed; pnpm lint passed with no warnings/errors; source backend/.venv/bin/activate && ruff format --check v2 passed; ruff check v2 passed; focused backend tests rerun passed (4 passed).
- 2026-06-13T11:59:59: Manual check skipped: scripts/local_test_stack.sh app failed before starting app services because NEXT_PUBLIC_FIREBASE_API_KEY is missing in frontend/.env.local/export. scripts/local_test_stack.sh status shows backend/frontend stopped; MongoDB/Firebase emulator were already running.
- 2026-06-13T12:07:06: RED spec-review regression: source backend/.venv/bin/activate && pytest v2/tests/interface/test_admin_teaching_plan.py -q -> 1 failed, 3 passed; template occurrence returned session-001 instead of template-session-001.
- 2026-06-13T12:08:02: Spec-review fix GREEN: source backend/.venv/bin/activate && pytest v2/tests/interface/test_admin_teaching_plan.py v2/tests/interface/test_admin_progress_routes.py::test_coach_engagement_stats_route_returns_counts_for_date_range -q -> 5 passed; ruff format --check and ruff check on touched admin teaching-plan route/test passed.
- 2026-06-13T12:21:50: Quality review fix verification: backend/.venv pytest v2/tests/interface/test_admin_teaching_plan.py v2/tests/interface/test_admin_progress_routes.py::test_coach_engagement_stats_route_returns_counts_for_date_range v2/tests/interface/test_admin_progress_routes.py::test_coach_engagement_stats_repo_ignores_not_started_placement_rows v2/tests/contract/test_student_progress_engagement_indexes.py -q (7 passed); backend/.venv ruff format --check v2 and ruff check v2 passed; frontend pnpm typecheck and pnpm lint passed.
## Reusable Lessons

- None recorded yet.
