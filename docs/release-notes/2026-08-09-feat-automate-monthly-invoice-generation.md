# feat-automate-monthly-invoice-generation

PR: #TBD

## What changed
Monthly invoices are now generated automatically (issue #288). Previously
nothing on the schedule called `generate_monthly_payments` — it only ran when
an admin clicked it — which is why no invoices were created on 2026-07-01.

- New scheduler job `generate_monthly_invoices` in `backend/v2/main.py`, held
  under a 30-minute distributed `job_lease` so exactly one Fly machine runs a
  pass. The cron ticks **daily** at 03:00 in `settings.scheduler_tz`; each
  academy is generated for only on its own `billing_day`.
- New `billing_settings.billing_day` (1–28, default 1) and
  `billing_settings.invoice_due_days` (0–60, default 7). `billing_day` is
  capped at 28 so no academy silently skips February.
- New audited admin routes `GET`/`PUT
  /api/v2/admin/billing/settings/invoice-schedule`, writing an
  `invoice_schedule_changed` billing-audit entry **before** the settings write,
  matching `SetPlatformChargeFallback`.
- Invoice `due_date` is now `generation date + invoice_due_days` instead of the
  period's last day, so a late or backfilled period still gets the full grace
  window before the first autopay attempt.

The first autopay charge is deliberately **not** scheduled here. Issue #288's
body is stale on that point: `ProcessDunningRetries` already seeds a dunning
state for every open invoice past its `due_date`, and `DUNNING_SCHEDULE_DAYS`
begins at `0` — that leading zero *is* the first charge attempt. A second
trigger would risk double-charging saved cards.

Also folded in: `ruff check`/`ruff format` fixes for four test files that were
already failing lint on `main` and would otherwise turn this PR's CI red.

## Deploy notes
No migration. `billing_settings` documents without the new fields fall back to
the model defaults (`billing_day=1`, `invoice_due_days=7`), so existing
academies begin generating on the 1st with no admin action.

**Verify after deploy:** `billing_day` is compared against the *scheduler*
timezone, not each academy's local timezone. Confirm `SCHEDULER_TZ` is set to
the operating timezone — if it is UTC while academies are US-Central, the
03:00 UTC tick on the 1st is 22:00 on the last day of the prior month locally.
On the first run, check for the `monthly_invoices_generated` log line and its
`created` / `skipped_existing` counts.

## Risk / rollback
Medium. This is the first code path that creates invoices without a human in
the loop, so a wrong `billing_day` or timezone generates real invoices on the
wrong date for real parents. Generation itself is idempotent — deterministic
invoice ids plus the `billing_invoice_keys` guard mean a re-run reports
`skipped_existing` rather than duplicating — and a per-academy failure is
logged and skipped without aborting the run.

Roll back by reverting this PR: the scheduler job disappears and generation
returns to admin-triggered only. To stop generation without a deploy, set an
academy's `billing_day` to a day that has already passed this month via the new
admin route. Invoices already created are not removed by a rollback; void them
through the existing admin invoice tooling.
