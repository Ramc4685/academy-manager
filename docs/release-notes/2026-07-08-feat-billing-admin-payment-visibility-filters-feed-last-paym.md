# feat-billing-admin-payment-visibility-filters-feed-last-paym

PR: #294

## What changed
Phase 1 of the approved 3-phase admin payment-visibility initiative (spec: `docs/superpowers/specs/2026-07-08-admin-payment-visibility-design.md`). Lets an owner/admin answer **who paid last, what payments came in, and when** — the top gap found in the payment-visibility audit.

### Backend
- `GET /admin/payments` now supports **date range** (on effective paid date), **status**, **method**, **name/invoice search** (`q`), and **limit/offset pagination**; rows sort by payment date (most recent money first) and now include `paid_at` and `parent_name` (enriched via the existing users lookup). Falls back to the legacy unfiltered path when the new use case isn't wired, so existing tests/mocks keep working.
- New `GET /admin/payments/feed` — latest money-received events merged from `ledger_payments` + legacy `payments` (deduped by provider keys), with parent names.
- New `GET /admin/payments/last-by-family` — most recent payment per parent, answering "who paid last" per family.
- Note: revenue-source unification (spec item 4) turned out to be **already done** — `/finance/revenue` is wired to `_AdminEffectiveRevenueQuery` which merges ledger + legacy with dedup; no change needed.

### Frontend
- **/admin/payments**: search box (debounced), paid-date range, status and method filters, "Paid on" column, parent name under student, page-based pagination past the old 200-row cap.
- **/admin/reports** (owner dashboard): new **Recent payments** card (last 10 money-received events with payer, amount, method, date) linking to the payments page.

## Deploy notes
No migration detected in the diff. Confirm no manual env var or manual step is needed before merge.

## Risk / rollback
_Auto-generated stub — author: fill in what breaks if this is wrong and how
to roll back before merge._ Revert the merge commit if this regresses.
