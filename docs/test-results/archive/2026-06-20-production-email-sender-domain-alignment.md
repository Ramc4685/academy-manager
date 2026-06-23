# production email sender domain alignment

## Current State

Status: active

## Problem

Verify production campaigns use the verified courtmastr.com sender instead of deriving the unverified academy.courtmastr.com sender

## Changed Files

- None recorded yet.

## Log

- 2026-06-20T06:56:08 main/NA: Task ledger created.
- 2026-06-20T06:57:02 main/working: Added v2 sender_email config with SENDER_EMAIL fallback and wired Resend composition to prefer the explicit verified sender over deriving noreply@academy.courtmastr.com from FRONTEND_URL. Set Fly SENDER_EMAIL/V2_SENDER_EMAIL to BLNO Badminton Academy <noreply@courtmastr.com>.
- 2026-06-20T06:59:19 main/working: Deployed isolated backend image from /tmp/academy-manager-email-sender with only the sender_email patch; did not deploy unrelated dirty workspace files.
## Verification

- No verification recorded yet.
- 2026-06-20T06:59:43: Focused local checks passed: temp isolated tree pytest v2/tests/unit/test_settings.py -q passed (15 passed); workspace pytest backend/v2/tests/unit/test_settings.py -q passed (18 passed). Production checks passed: public /api/v2/healthz returned {"status":"ok"}; flyctl checks list passing; runtime Settings reports sender_email=BLNO Badminton Academy <noreply@courtmastr.com>, email_delivery_enabled=True, resend_api_key present; deployed sender-path Resend test to RamC.Venkatasamy@gmail.com returned message id 449a7de3-515e-49ce-b922-70c3f9fe65a4.
## Reusable Lessons

- None recorded yet.
