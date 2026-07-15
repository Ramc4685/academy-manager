# Registration review concurrency hardening

## Current State

Status: active

## Problem

Close code-review and security-review gaps in duplicate-child matching and concurrent admin decisions before publishing the registration defect fixes.

## Changed Files

- `backend/v2/composition/admin_registration_review.py`
- `backend/v2/contexts/onboarding/application/use_cases/manage_application.py`
- `backend/v2/contexts/enrollment/infrastructure/mongo_student_repo.py`
- `backend/v2/contexts/onboarding/infrastructure/mongo_application_repo.py`

## Log

- 2026-07-14T12:14:35 main/NA: Task ledger created.

## Verification

- No verification recorded yet.
- 2026-07-14T12:14:35: backend/.venv/bin/python -m pytest focused application/repository set: 44 passed; broader backend application and affected contract set: 662 passed with 1 existing mongomock warning.
- 2026-07-14T12:32:07: Final backend: 45 focused tests and 2,420 full-suite tests passed; Ruff and all 5 import-linter contracts passed. Frontend unit tests, typecheck, and lint passed. Full Playwright run: 207 passed, 174 skipped, with one unrelated wrong-role WebKit timeout that passed on retry; after using DOMContentLoaded navigation, both wrong-role WebKit tests passed. Registration approval and child-added staging checks were previously captured in the archived ledgers.
## Reusable Lessons

- None recorded yet.
