# autopay slice v parent visibility

## Current State

Status: active

## Problem

R6 parent visibility should use app-owned autopay projections, not retired Stripe subscription status: parent enrollments expose per-enrollment autopay status/outcome and ACH/card method so the parent payments page can show accurate state.

## Changed Files

- `backend/v2/interfaces/parent/views.py`
- `backend/v2/composition/parent.py`
- `backend/v2/tests/interface/test_parent_activity_routes.py`
- `backend/v2/tests/unit/test_parent_composition.py`
- `frontend/lib/api/parent.ts`
- `frontend/app/(parent)/parent/payments/page.tsx`
- `frontend/lib/parent-billing-recovery-ui.node-test.mjs`

## Log

- 2026-07-01T13:47:52 main/NA: Task ledger created.
- 2026-07-01T13:49:33 main/working: Added RED tests for R6 parent visibility: parent enrollments must expose app-owned autopay status/outcome/method fields and frontend must render those fields instead of subscription wording.
- 2026-07-01T13:52:52 main/working: Implemented R6 parent visibility: parent enrollment DTO/composition now exposes app-owned autopay enrollment status, last attempt projection, failure code, primary method type, and setup status; parent payments UI uses these fields and ACH/card copy instead of subscription status wording.
- 2026-07-01T13:58:08 main/working: Addressed reviewer findings: setup-pending banner now uses app-owned autopay_enrollment_status, method copy is suppressed outside monthly active/paused/setup-started autopay states, and frontend static regression checks cover both guards.
## Verification

- No verification recorded yet.
- 2026-07-01T13:49:34: RED: source /Users/ramc/Documents/Code/academy-manager/backend/.venv/bin/activate && PYTHONPATH=. python -m pytest backend/v2/tests/interface/test_parent_activity_routes.py::test_enrollments_expose_app_owned_autopay_visibility_fields backend/v2/tests/unit/test_parent_composition.py::test_parent_enrollment_visibility_uses_app_owned_autopay_projection -q => 2 failed as expected (missing autopay fields). node --no-warnings --test frontend/lib/parent-billing-recovery-ui.node-test.mjs => 1 failed as expected (frontend API/page lacks autopay_enrollment_status/app-owned copy).
- 2026-07-01T13:52:52: Focused GREEN: source /Users/ramc/Documents/Code/academy-manager/backend/.venv/bin/activate && PYTHONPATH=. python -m pytest backend/v2/tests/interface/test_parent_activity_routes.py backend/v2/tests/unit/test_parent_composition.py -q => 20 passed, 1 existing Starlette/httpx warning. node --no-warnings --test frontend/lib/parent-billing-recovery-ui.node-test.mjs => 3 passed. pnpm typecheck => passed. Touched backend ruff check/format => passed.
- 2026-07-01T13:52:52: DoD: PYTHONPATH=. python -m pytest backend/v2/tests -q => 1976 passed, 1 failed: known cwd-path FileNotFoundError in test_bootstrap_source_does_not_reference_default_academy_id; confirmed from backend/ with PYTHONPATH=.. python -m pytest v2/tests/application/test_bootstrap_academy.py::test_bootstrap_source_does_not_reference_default_academy_id -q => 1 passed. ruff check backend/v2 => passed. ruff format --check backend/v2 => 755 files already formatted. lint-imports --config backend/pyproject.toml => 4 contracts kept. pnpm lint => 0 errors, 5 existing warnings.
- 2026-07-01T14:00:22: Final DoD after reviewer fix: PYTHONPATH=. python -m pytest backend/v2/tests -q => 1976 passed, 1 known cwd-path FileNotFoundError in test_bootstrap_source_does_not_reference_default_academy_id. ruff check backend/v2 => passed. ruff format --check backend/v2 => 755 files already formatted. lint-imports --config backend/pyproject.toml => 4 contracts kept. pnpm lint => 0 errors, 5 existing warnings. Reviewer re-review approved.
- 2026-07-01T14:00:29: Known failure confirmation: from backend/ with PYTHONPATH=.. python -m pytest v2/tests/application/test_bootstrap_academy.py::test_bootstrap_source_does_not_reference_default_academy_id -q => 1 passed.
## Reusable Lessons

- None recorded yet.
