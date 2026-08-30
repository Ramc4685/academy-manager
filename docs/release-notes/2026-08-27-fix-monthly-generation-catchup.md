# fix(billing): catch-up window for monthly invoice generation

PR: #440

## What changed

The daily monthly-invoice generation job only generated when
`billing_settings.billing_day == now.day`. A single failed 03:00 run on an
academy's billing day (Mongo blip, lease handover, crash before the per-academy
try) meant the next daily tick saw `billing_day != now.day` and skipped — the
entire month was silently never invoiced, recoverable only by an admin.

- The gate is now "billing_day has passed **and** no successful generation is
  recorded for the period". A failed run self-heals on the next daily tick
  instead of skipping a month.
- Each tick considers **two** periods: the current one, and the immediately
  prior one when it is unrecorded. Without the prior period the catch-up window
  would end at month end — a `billing_day=28` academy in February would still
  get exactly one attempt, and a failure spanning the month boundary would lose
  that month forever. Prior-period catch-up is gated on the academy having some
  generation history, so a first deploy or a newly onboarded academy is never
  retro-invoiced for a month it may not have been enrolled in.
- Success is recorded per `(academy_id, period)` in a new
  `billing_generation_runs` collection. The record is a scheduling
  stop-condition, not an invoice guard: duplicate invoices are still prevented
  by the deterministic invoice ids plus the `billing_invoice_keys` unique index,
  so a lost record only costs a redundant pass that re-reports
  `skipped_existing`. It also keeps the pre-existing behaviour that enrollments
  created *after* billing_day are not retro-invoiced for the current period.
- A run that returns normally but reports `failed_repair > 0` is **not**
  recorded. `generate_monthly_payments` swallows per-enrollment repair failures
  and returns, so recording success there would switch off the daily retry for
  exactly the enrollments that still need it. Such runs log
  `monthly_invoice_generation_partial` and are re-attempted next tick.
- The run-record write lives outside the generation `try` and never raises. A
  `DuplicateKeyError` (two machines racing the new unique index across a lease
  handover) is treated as benign; any other write blip logs
  `monthly_generation_run_record_failed` and leaves the period to be re-attempted
  idempotently. Neither can masquerade as a generation failure or drop the
  academy from the run summary.
- The `billing_settings` read moved inside the per-academy `try`, so one
  academy's unreadable settings document can no longer abort generation for
  every academy after it. On a read failure the academy now falls back to the
  **default** `billing_day` rather than being skipped — matching the billing
  context's own rule that settings "must never block the monthly run" (see
  `MongoMonthlyBilling._load_invoice_due_days`). Skipping would have turned an
  unreadable settings doc into a permanent silent skip, the exact failure mode
  this issue set out to remove.
- A catch-up run that actually creates invoices logs a distinct
  `monthly_invoices_generated_by_catch_up` warning.
- Timezone semantics are unchanged: `billing_day` is still interpreted in the
  scheduler timezone (`settings.scheduler_tz`), not each academy's local
  timezone. Dunning is untouched.
- Incidental fix: both summary log lines passed `created` in `extra`, which
  `logging` refuses (reserved `LogRecord` attribute) and raises `KeyError` on —
  the `monthly_invoices_generated` line would throw out of the job on any run
  that generated something. The key is now `created_count`.

  **Correction to an earlier note:** `2026-08-09-feat-automate-monthly-invoice-generation.md`
  (line 40) tells operators to check the `created` field on the
  `monthly_invoices_generated` log line. That field is now `created_count`;
  repoint any dashboard, alert, or log query built from that instruction.

New migration `0151_billing_generation_runs` creates a unique index on
`(academy_id, period)` for `billing_generation_runs`.

Closes #431.

## Deploy notes

- Run migrations on deploy as usual; `0151` only creates an index on a new,
  empty collection.
- **First-run implication (Sept 1):** the `billing_generation_runs` collection
  starts empty, so on the first daily tick after deploy every academy whose
  `billing_day` has already passed in the current period will be treated as
  "not yet generated" and will run generation once for that period. This is
  safe — `generate_monthly_payments` is idempotent, so for a period already
  invoiced the pass reports `skipped_existing` and creates nothing. Expect one
  extra full enrollment walk per academy on that first tick, and expect
  `monthly_invoices_generated_by_catch_up` warnings only if a period genuinely
  had missing invoices. If deployed before Sept 1, the first clean cycle is the
  Sept 1 03:00 run, which behaves exactly as before.
  Prior-period backfill does **not** happen on this first tick: with no
  generation history recorded for any academy, the prior-period window is
  deliberately inert until each academy has one recorded run.
- **Lowering `billing_day` mid-month now generates immediately.** Under the old
  exact-day gate, changing an academy's `billing_day` from 20 to 5 on the 18th
  did nothing that month — the 5th had already passed and would never match
  again. Under the new gate the 5th *has passed* and the period is unrecorded,
  so the next 03:00 tick generates the current month's invoices for real. Warn
  admins that a mid-month `billing_day` reduction is now an immediate billing
  action, not a change that takes effect next month.
- **Catch-up shifts `due_date`, and with it the dunning ladder.** `due_date` is
  the generation date plus `invoice_due_days`, so an invoice generated three
  days late is due three days late — and the whole autopay/dunning ladder for
  that month slides by the same lateness, since the ladder is anchored on
  `due_date` (`DUNNING_SCHEDULE_DAYS` starts at 0). This is intentional (every
  invoice keeps its full grace window) but means a late month collects later.
- No new environment variables or feature flags.

## Risk / rollback

- **Risk: low.** Generation itself is untouched; only the scheduler's decision
  to call it changed. The worst case of the new gate is a redundant idempotent
  pass, not a duplicate charge — no charge path was modified and dunning was
  not touched.
- The main behaviour-change risks to watch are the two Deploy-notes items
  above: mid-month `billing_day` reductions now bill immediately, and catch-up
  runs shift that month's due dates and dunning schedule.
- Watch after deploy: `monthly_invoices_generated_by_catch_up` (should be rare;
  each occurrence means a billing-day run had failed),
  `monthly_invoice_generation_partial` (a run created invoices but left repairs
  failing — investigate before it repeats), `monthly_invoice_generation_failed`
  and `monthly_invoice_generation_gate_failed`, and
  `monthly_generation_billing_settings_unreadable` (an academy is now running on
  the default `billing_day`).
- Rollback: revert the commit. The `billing_generation_runs` collection and its
  index become inert and can be left in place; the previous exact-day gate
  ignores them entirely.
