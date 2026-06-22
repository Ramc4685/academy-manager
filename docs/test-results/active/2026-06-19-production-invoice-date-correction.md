# production invoice date correction

## Current State

Status: active

## Problem

Verify production invoice dates for April, May, and June invoices and prepare a safe correction plan before any approved production DB write.

## Changed Files

- None recorded yet.

## Log

- 2026-06-19T22:57:06 main/NA: Task ledger created.
- 2026-06-19T22:57:43 main/working: Starting read-only production invoice date audit for 2026-04, 2026-05, and 2026-06. No production writes authorized or planned in this step.
- 2026-06-19T23:03:17 main/working: User approved production DB date-only correction so June invoices display as generated on 2026-06-01. Scope: app Mongo date fields only; no Stripe, amount, status, or payment collection semantics change.
- 2026-06-19T23:19:36 main/working: User reported invoice dates display one day earlier after production DB date correction. Investigating frontend date rendering/timezone behavior before any further production writes.
## Verification

- No verification recorded yet.
- 2026-06-19T23:01:17: Read-only production audit via Fly SSH against academy_manager/acad_blno_badminton. April payments: 36 all created/due 2026-04-01. May payments: 44 all created/due 2026-05-01. June payments: 45 total, 5 created/due 2026-06-01 and 40 created 2026-06-11 with missing due_date. June ledger invoices: 1 paid Stripe subscription invoice created 2026-06-19, due 2026-07-19, with one line created 2026-06-19. No production writes run.
- 2026-06-19T23:04:03: Production DB update completed after user approval. Matched/modified: payments 45/45, invoices 1/1, invoice_lines 1/1 for academy_id=acad_blno_badminton and June 2026. Post-update readback: payments created_dates={2026-06-01:45}, due_dates={2026-06-01:45}, missing_due=0; invoices created_dates={2026-06-01:1}, due_dates={2026-06-01:1}; invoice_lines created_dates={2026-06-01:1}. Stripe objects, amounts, statuses, allocations, and payment collection state were not changed.
## Reusable Lessons

- None recorded yet.
