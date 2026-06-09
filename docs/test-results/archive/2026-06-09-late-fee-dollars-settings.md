# late fee dollars settings

## Current State

Status: active

## Problem

Settings Fees panel shows late_fee_cents as cents; admins should enter/view late fee in dollars while API continues storing cents.

## Changed Files

- None recorded yet.

## Log

- 2026-06-09T08:53:39 main/NA: Task ledger created.
- 2026-06-09T08:56:03 main/working: Changed fees panel late fee input to display dollars while converting PATCH payload back to cents; updated E2E expectation.
## Verification

- No verification recorded yet.
- 2026-06-09T09:00:56: RED: PLAYWRIGHT_PORT=3121 pnpm exec playwright test e2e/specs/admin-session-creation-ui.spec.ts --project=chromium-mobile --grep 'fee settings focus' failed because getByLabel('Late fee ($)') did not exist.
- 2026-06-09T09:00:56: GREEN: same focused Playwright E2E passed; it verifies Late fee ($) displays 15.00 from 1500 cents and PATCHes 17.50 dollars as late_fee_cents: 1750.
- 2026-06-09T09:00:56: Browser DOM verification at http://blno.localhost:3001/admin/settings?panel=fees showed labels Late fee ($) and Grace days, no Late fee cents label, no framework overlay, and filling 12.34 enabled Save changes. Browser screenshot failed with CDP Page.captureScreenshot timeout; OS screenshot unavailable.
## Reusable Lessons

- None recorded yet.
