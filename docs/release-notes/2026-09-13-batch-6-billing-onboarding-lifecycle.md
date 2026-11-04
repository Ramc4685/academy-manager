# batch-6-billing-onboarding-lifecycle

PR: #803

## What changed

- Fixes #537 — The 7-day application TTL was never enforced: nothing ever checked whether a DRAFT/CHECKOUT_PENDING `Application` had gone stale, so a parent could resume (or an admin could re-serve) a week-old draft indefinitely. Added `Application.is_expired(now)` to the domain model (DRAFT/CHECKOUT_PENDING only, tz-naive-safe). `StartApplication` now retires an expired existing application to `ABANDONED` and creates a fresh one instead of handing the stale draft back. `PatchApplication` now raises `ApplicationNotEditable` on an expired draft. `start_checkout_for_application` in `composition/parent.py` now rejects an expired DRAFT/CHECKOUT_PENDING before any Stripe/Payment side effect, using the already-injected clock — so no expired application can reach checkout.
- Fixes #552 — `late_fee_cents` and `grace_days` were editable academy billing settings that nothing ever read, so overdue invoices never accrued a late fee no matter how the settings were configured. Added an `ApplyLateFees` use case; the dunning scheduler tick now runs it first, per academy, inside the existing tenant scope, before the existing retry/notice pass (the fee raises `balance_due_cents`, so a dunning notice sent in the same tick quotes the new total). A late fee is written as an `invoice_lines` row with `source_type: "late_fee_policy"`; a partial unique index (migration 0181) makes "already charged a late fee this invoice" a store-level invariant instead of a check-then-add race between overlapping scheduler ticks. The admin manual-invoicing line-type picker gained a `late_fee` option so a hand-entered late fee lands on the same type the automation recognizes, avoiding a double charge.
- Failures in the late-fee pass are logged and never fatal — they must not cost an academy its dunning retries for that tick.

## Deploy notes

Includes one migration:
- `backend/v2/migrations/0181_late_fee_line_unique_index.py` — partial unique index on `invoice_lines` scoped to `source_type == "late_fee_policy"`, preventing double-charging a late fee on the same invoice. No pre-existing documents can carry that `source_type`, so the index build cannot meet a duplicate; a `DuplicateKeyError` on build is still caught defensively (mirrors migration 0174), never crashes boot.

Production does not run migrations on boot (`V2_RUN_MIGRATIONS_ON_BOOT` is false, #629) — apply this migration by hand via `run_pending_migrations` per AGENTS.md, ideally before or at deploy so the invariant is live before the first scheduler tick that could apply a late fee.

No other manual env var or config changes.

## Risk / rollback

#537 changes onboarding-application lifecycle behavior (expiring stale drafts to `ABANDONED`, blocking checkout and edits on expired applications) — covered by new unit tests in `test_onboarding_ownership.py`. #552 introduces a new money-moving automated pass (adds real dollar amounts to real invoices) gated by academy settings that already existed but were previously inert; it is covered by `test_apply_late_fees.py` and `test_overdue_invoice_queries.py`, and protected against double-application by the new partial unique index. If either regresses in prod, revert this PR's merge commit; migration 0181 is additive (index-only, no data rewrite) and does not need a separate rollback — dropping it only removes the double-charge guard, it does not need to precede a code revert.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
