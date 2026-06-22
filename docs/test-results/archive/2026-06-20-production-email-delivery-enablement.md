# production email delivery enablement

## Current State

Status: active

## Problem

Verify admin email campaigns can use the real Resend sender in production without enabling local/test delivery

## Changed Files

- None recorded yet.

## Log

- 2026-06-20T06:06:11 main/NA: Task ledger created.
- 2026-06-20T06:07:08 main/working: Changed production Fly env from unprefixed EMAIL_DELIVERY_ENABLED=false to V2_EMAIL_DELIVERY_ENABLED=true, added Settings fallback for legacy EMAIL_DELIVERY_ENABLED, and documented the v2 flag.
## Verification

- No verification recorded yet.
- 2026-06-20T06:07:34: cd backend && source .venv/bin/activate && pytest v2/tests/unit/test_settings.py -q passed (16 passed).
## Reusable Lessons

- None recorded yet.
