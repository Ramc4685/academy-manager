# autopay slice h dunning ladder

## Current State

Status: active

## Problem

App-owned autopay retry/dunning ladder: schedule/state, worker, parent notifications, admin visibility, terminal disabled automation, tenant-safe/idempotent verification.

## Changed Files

- None recorded yet.

## Log

- 2026-07-01T12:41:39 main/NA: Task ledger created.
- 2026-07-01T12:41:39 main/working: Slice H worktree created at .worktrees/slice-h from main 24b73dd3; migration 0143 assigned for dunning state/indexes if needed. Preparing implementer dispatch.
- 2026-07-01T12:44:28 main/working: Kickoff read complete: Headroom available; required repo docs and Slice H plan read; required docs/requirements/2026-06-30-autopay-ach-card-fee-requirements-review-v2.md is absent in this worktree. Found existing charge use case records failed attempts and gates on per-enrollment active autopay; dunning will extend v2 billing DDD with RED tests first.
- 2026-07-01T12:52:38 main/working: Implemented Slice H dunning ladder: domain state machine day 0/3/5/7; tenant-scoped dunning_states projection with claim/finish/notification markers; scheduler worker invoking ChargeInvoiceViaAutopay; terminal dunned disables enrollment autopay; admin /billing/dunning view; migration 0143 indexes/validator; RED/GREEN and DoD evidence recorded.
## Verification

- No verification recorded yet.
- 2026-07-01T12:47:00: RED: source backend/.venv/bin/activate && PYTHONPATH=. python -m pytest backend/v2/tests/unit/test_dunning_ladder.py backend/v2/tests/application/test_dunning_worker.py backend/v2/tests/contract/test_dunning_state_repo.py backend/v2/tests/interface/test_admin_billing.py::test_list_dunning_failures -q failed with ModuleNotFoundError for billing.domain.dunning, process_dunning_retries, and mongo_dunning_state_repo as expected before implementation.
- 2026-07-01T12:50:41: GREEN focused Slice H: source backend/.venv/bin/activate && PYTHONPATH=. python -m pytest backend/v2/tests/unit/test_dunning_ladder.py backend/v2/tests/application/test_dunning_worker.py backend/v2/tests/contract/test_dunning_state_repo.py backend/v2/tests/interface/test_admin_billing.py::test_list_dunning_failures backend/v2/tests/unit/test_scheduler_academies.py::test_scheduler_registers_dunning_retry_job -q => 11 passed, 1 Starlette/httpx deprecation warning.
- 2026-07-01T12:50:59: Focused regression: PYTHONPATH=. python -m pytest backend/v2/tests/interface/test_admin_billing.py backend/v2/tests/unit/test_charge_autopay_use_case.py backend/v2/tests/unit/test_scheduler_academies.py -q => 109 passed, 1 Starlette/httpx deprecation warning.
- 2026-07-01T12:52:19: DoD: PYTHONPATH=. python -m pytest backend/v2/tests -q => 1958 passed, 1 failed (known allowed bootstrap cwd-path FileNotFoundError in test_bootstrap_source_does_not_reference_default_academy_id), 5 warnings. ruff check backend/v2 => pass. ruff format --check backend/v2 => 755 files already formatted. lint-imports --config backend/pyproject.toml => 4 contracts kept, 0 broken.
## Reusable Lessons

- None recorded yet.
