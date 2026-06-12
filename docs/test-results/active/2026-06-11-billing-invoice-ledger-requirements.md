# billing invoice ledger requirements

## Current State

Status: active

## Problem

Clarify admin payment screen semantics and define feature requirements for automated monthly invoices, autopay collection, reminder email, and payment ledger workflows.

## Changed Files

- None recorded yet.

## Log

- 2026-06-11T14:01:51 main/NA: Task ledger created.
- 2026-06-11T14:02:01 main/working: Inspected admin Payments UI, admin billing routes, payments repository, billing ledger repository, dues follow-up routes, scheduler wiring, and relevant active ledgers. Producing requirements/features only; no code changes.
- 2026-06-11T14:55:26 main/working: User clarified that autopay parents must also receive invoice email; invoices should be generated and communicated before/with collection, not replaced by receipts only.
- 2026-06-11T15:09:17 main/working: User clarified billing timing: generate monthly invoices on the 1st, send invoice emails, and immediately attempt autopay collection for autopay-enabled parents.
- 2026-06-11T15:13:27 main/working: User clarified non-autopay invoice email should include Stripe online payment, ask parent to enable autopay, and provide Zelle fallback to 248-885-9243.
- 2026-06-11T15:21:40 main/working: User clarified Zelle/manual payments are not parent-confirmed; admin manually marks them paid after receipt.
- 2026-06-11T15:32:38 main/working: User clarified Stripe invoice-link payments are one-time payments only; autopay remains off unless the parent explicitly enables it.
## Verification

- No verification recorded yet.
- 2026-06-11T14:02:01: No tests run; requirements analysis only. Code inspection covered frontend admin payments page, dues page, admin API client, billing routes, payment repository, billing ledger repository, and scheduler wiring.
## Reusable Lessons

- None recorded yet.
