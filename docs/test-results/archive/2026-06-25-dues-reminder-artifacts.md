# dues reminder artifacts

## Current State

Status: active

## Problem

Dues reminder action should not generate invoice artifacts when sending/blocked reminders

## Changed Files

- None recorded yet.

## Log

- 2026-06-25T17:13:27 main/NA: Task ledger created.

## Verification

- No verification recorded yet.
- 2026-06-25T17:17:07: RED: focused dues reminder tests initially failed because SendDuesRemindersCommand defaulted generate_invoice_artifacts=True and route returned generated_invoice_artifacts=2. GREEN: after defaulting generate_invoice_artifacts=False and fixing the app fake, backend/.venv/bin/python -m pytest backend/v2/tests/application/test_dues_reminders.py backend/v2/tests/interface/test_admin_payment_dues_routes.py -q passed: 8 passed, 1 StarletteDeprecationWarning.
## Reusable Lessons

- None recorded yet.
