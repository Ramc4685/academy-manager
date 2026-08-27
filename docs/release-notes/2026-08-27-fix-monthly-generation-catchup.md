# fix(billing): catch-up window for monthly invoice generation

PR: #440

## What changed

The daily monthly-invoice generation job only generated when
`billing_settings.billing_day == now.day`. A single failed 03:00 run on an
academy's billing day (Mongo blip, lease handover, crash before the per-academy
try) meant the next daily tick saw `billing_day != now.day` and skipped — the
entire month was silently never invoiced, recoverable only by an admin.

- The gate is now "billing_day has passed in the current period **and** no
  successful generation is recorded for that period". A failed run self-heals
  on the next daily tick instead of skipping a month.
- Success is recorded per `(academy_id, period)` in a new
  `billing_generation_runs` collection, written only after
  `generate_monthly_payments` returns without raising. The record is a
  scheduling stop-condition, not an invoice guard: duplicate invoices are still
  prevented by the deterministic invoice ids plus the `billing_invoice_keys`
  unique index, so a lost record only costs a redundant pass that re-reports
  `skipped_existing`. It also keeps the pre-existing behaviour that enrollments
  created *after* billing_day are not retro-invoiced for the current period.
- The `billing_settings` read moved inside the per-academy `try`, so one
  academy's unreadable or invalid settings document can no longer abort
  generation for every academy after it in the loop.
- A catch-up run that actually creates invoices now logs a distinct
  `monthly_invoices_generated_by_catch_up` warning with `billing_day`,
  `run_day`, and the created count; the existing `monthly_invoices_generated`
  summary is unchanged in content.
- Incidental fix in the same function: both summary log lines passed `created`
  in `extra`, which `logging` refuses (reserved `LogRecord` attribute) and
  raises `KeyError` on. The key is now `created_count`. Alerting or log queries
  keyed on `created` need to be repointed.
- Timezone semantics are unchanged: `billing_day` is still interpreted in the
  scheduler timezone (`settings.scheduler_tz`), not each academy's local
  timezone.

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
- No new environment variables or feature flags.

## Risk / rollback

- **Risk: low.** Generation itself is untouched; only the scheduler's decision
  to call it changed. The worst case of the new gate is a redundant idempotent
  pass, not a duplicate charge — no charge path was modified and dunning was
  not touched.
- Watch after deploy: `monthly_invoices_generated_by_catch_up` (should be rare;
  each occurrence means a billing-day run had failed) and
  `monthly_invoice_generation_failed` (unchanged semantics, now also covers a
  failed `billing_settings` read for a single academy).
- Rollback: revert the commit. The `billing_generation_runs` collection and its
  index become inert and can be left in place; the previous exact-day gate
  ignores them entirely.
