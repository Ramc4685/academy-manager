# feat-reports-owner-financial-dashboard-phase-2

PR: #295

## What changed
Phase 2 of the admin payment-visibility initiative (spec: `docs/superpowers/specs/2026-07-08-admin-payment-visibility-design.md`). Builds the industry-standard (Jackrabbit Executive Dashboard pattern) owner financial dashboard on **/admin/reports**. Stacked on #294 (Phase 1).

### Backend
- `get_reports_dashboard` now returns **`billed_cents`** and **`collection_rate`** (cash-basis; billed deduped against legacy `payments` via provider keys, same as outstanding), and each AR-aging bucket carries a **`families`** drill-down list (family id, tenant-scoped display name, amount).
- New `GET /admin/reports/projected-income?period=YYYY-MM` — next-month expected tuition: active enrollments × session monthly fee (per-student `override_price_cents` wins), **split autopay vs manual** via `student_billing_enrollments.autopay_enrollment_status == "active"`, with a per-session breakdown.
- Revenue trend reuses the already-unified `/finance/revenue`; no new endpoint.

### Frontend (/admin/reports)
- Stat tiles: **Billed / Collected / Outstanding / Collection rate** for the selected month.
- **Failed-autopay alert card** front and center when failures exist: count + total $, per-row **Retry charge** (existing charge-autopay endpoint; shows decline code / 3DS outcome) and **Notify parent** (dues-reminders; UI surfaces `blocked` / `sent: 0` instead of claiming success).
- **AR aging widget**: expandable Current/1-30/31-60/60+ buckets → family list with amounts and per-family **Send reminder**.
- **Projected income widget** for next month with autopay/manual split bar and per-session table.
- **Revenue trend chart** (Recharts): monthly, this year vs prior year.

## Deploy notes
No migration in the diff; new endpoint is additive and 503-guards when not wired. No env vars or manual steps.

## Risk / rollback
Read-only aggregations plus reuse of existing admin actions; worst case is a wrong number on the dashboard, not a billing mutation. Revert the merge commit to roll back. Known v1 limitation: projected-income `period` labels the response but the projection always reflects currently-active enrollments.
