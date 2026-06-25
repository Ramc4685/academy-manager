# production registration waiver unavailable hotfix

## Current State

Status: active

## Problem

Parents registering kids in production see waiver/not available to register and cannot complete registration

## Changed Files

- `backend/v2/contexts/onboarding/infrastructure/mongo_registration_waiver_repo.py`
- `backend/v2/tests/contract/test_registration_waiver_repo.py`
- `test_result.md`

## Log

- 2026-06-24T18:20:44 main/NA: Task ledger created.
- 2026-06-24T18:24:53 main/working: Root cause found and fixed: assigned legacy production waiver_templates rows with status=published were allowed by admin assignment but invisible to parent registration lookup, which only matched assigned status=active rows. Updated registration waiver resolver to match assigned active or published rows and added regression coverage.
## Verification

- No verification recorded yet.
- 2026-06-24T18:24:53: RED: pytest v2/tests/contract/test_registration_waiver_repo.py -q failed test_resolves_assigned_legacy_published_template_shape_from_production because waiver was None for assigned status=published row. GREEN: same command passed 7 tests. Focused suite passed 22 tests: registration waiver repo, parent onboarding waiver acceptance, admin waiver template management, waiver signatures repo. Ruff format --check and ruff check on touched backend files passed. Full backend pytest v2/tests -q passed 1589 tests with 5 existing warnings.
## Reusable Lessons

- None recorded yet.
