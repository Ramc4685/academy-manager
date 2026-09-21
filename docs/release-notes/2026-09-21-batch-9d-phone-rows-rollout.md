# batch-9d-phone-rows-rollout

PR: #858

## What changed

- Fixes #857 — Finished the `PhoneRow` rollout #856 started. Below `md`, thirteen admin lists now mount the shared `PhoneListRow` instead of a table in `overflow-x-auto`: the Registrations/Level-ups/Waitlist queues, all five parent-request queues, All invoices, Payroll, Payslips, Expenses, the billing-health webhook queue, the session roster, Class dates, and the family-detail Students and Invoices panels. Each phone row passes through the same status chips and `formatCents`/money values the desktop table already derived, so no list re-derives status or money independently, and money actions on phone reach the same dialogs through the same handlers as desktop. Payment eligibility is derived once and shared by both layouts.
- Also fixes a latent test-id collision left over from #856: admin-families/admin-users actions triggers no longer start with their own row id's prefix, so a prefix selector cannot mistake a trigger for a row; new lists use `<list>-actions-<id>` from the start. Level-ups moves to a new id-keyed row-actions helper, class dates gain a layout-agnostic row id, and three loose substring locators were made exact so existing specs keep their coverage on both mobile and desktop layouts.

## Deploy notes

Frontend-only changes. No new migrations, no new environment variables, no backend schema or endpoint changes.

## Risk / rollback

Low. Changes are additive/structural UI fixes (mounting the existing shared `PhoneListRow` component on more lists, plus test-id disambiguation) with no data or schema impact. Full backend gate (pytest, ruff check/format, lint-imports, mypy-baseline) and frontend gate (tsc, eslint, `next build --webpack`) pass on the branch. To roll back, revert this PR's merge commit.
