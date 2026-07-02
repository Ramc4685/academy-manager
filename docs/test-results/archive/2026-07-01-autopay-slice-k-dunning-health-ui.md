# autopay slice k dunning health ui

## Current State

Status: archived

## Problem

Extend existing admin billing-health UI to surface app-owned dunning ladder rows and autopay disable failures from Slice H.

## Changed Files

- `backend/v2/composition/admin.py`
- `backend/v2/tests/unit/test_admin_composition_tenancy.py`
- `frontend/app/(admin)/admin/billing-health/page.tsx`
- `frontend/e2e/specs/billing-health.spec.ts`
- `frontend/lib/api/admin.ts`
- `frontend/lib/query/keys.ts`

## Log

- 2026-07-01T14:47:59 main/NA: Task ledger created.
- 2026-07-01T14:54:23 main/done: Integrated Slice H dunning rows into /admin/billing-health, added terminal disable failure visibility, included dunning in health status/stat counts, and enriched dunning parent names in admin composition.

## Verification

- 2026-07-01T14:50:05: RED: pnpm exec playwright test e2e/specs/billing-health.spec.ts --grep 'renders all three sections' failed as expected on missing dunning-table before UI wiring.
- 2026-07-01T14:50:29: GREEN targeted: pnpm exec playwright test e2e/specs/billing-health.spec.ts --grep 'renders all three sections' -> 2 passed (chromium-mobile, webkit-mobile).
- 2026-07-01T14:51:05: Full billing-health e2e: pnpm exec playwright test e2e/specs/billing-health.spec.ts -> 8 passed. Frontend typecheck: pnpm typecheck -> passed.
- 2026-07-01T14:51:26: Frontend lint: pnpm lint -> passed with 5 pre-existing warnings outside touched Slice K files.
- 2026-07-01T14:53:05: RED backend: PYTHONPATH=. python -m pytest backend/v2/tests/unit/test_admin_composition_tenancy.py::test_admin_dunning_failures_enrich_parent_name_from_request_tenant -q failed as expected because dunning parent_name was None.
- 2026-07-01T14:54:00: Focused backend: PYTHONPATH=. python -m pytest backend/v2/tests/interface/test_admin_billing.py::test_list_dunning_failures backend/v2/tests/application/test_dunning_worker.py::test_terminal_disable_failure_is_recorded_and_retried backend/v2/tests/contract/test_dunning_state_repo.py::test_worker_with_real_mongo_repos_terminally_disables_enrollment backend/v2/tests/unit/test_admin_composition_tenancy.py::test_admin_dunning_failures_enrich_parent_name_from_request_tenant -q -> 4 passed, 1 existing Starlette/httpx warning. Backend ruff check/format on touched Python files passed.
- 2026-07-01T14:54:01: Final frontend e2e: pnpm exec playwright test e2e/specs/billing-health.spec.ts -> 8 passed after explicit dunning endpoint stubs.
- 2026-07-01T14:54:23: Final frontend static checks: pnpm typecheck -> passed; pnpm lint -> passed with 5 existing warnings outside touched files.
## Reusable Lessons

- None recorded yet.
