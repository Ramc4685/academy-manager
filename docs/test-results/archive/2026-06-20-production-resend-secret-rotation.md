# production resend secret rotation

## Current State

Status: active

## Problem

Verify Fly production has Resend API key configured and v2 email delivery enabled without committing secrets

## Changed Files

- None recorded yet.

## Log

- 2026-06-20T06:15:34 main/NA: Task ledger created.
- 2026-06-20T06:16:07 main/working: Set Fly secrets RESEND_API_KEY and V2_EMAIL_DELIVERY_ENABLED=true on courtmastr-academy-api. No secret values written to repo files.
## Verification

- No verification recorded yet.
- 2026-06-20T06:16:20: flyctl secrets list shows RESEND_API_KEY and V2_EMAIL_DELIVERY_ENABLED deployed; curl -fsS https://api.academy.courtmastr.com/api/v2/healthz returned {"status":"ok"}.
## Reusable Lessons

- None recorded yet.
