# batch-10b-payments-actions

PR: #0

## What changed

- Fixes #861 — All invoices rows rendered up to five direct action buttons per row, pushing Status/Method/Paid-on past the admin shell's ~944px content box at 1280. Rows now keep at most two action buttons (Invoice + Mark paid / Refund) plus a "More" overflow menu, in a width-capped sticky column (`w-[232px]`), both derived from one `paymentRowActions` list so the phone menu and the desktop strip cannot disagree about eligibility. The table's artificial `min-w-[980px]` floor dropped to `720px` so Status/Method/Paid-on stay visible in the space the admin shell leaves. The Refund dialog also now names the family/student/invoice/period being refunded, prefills and requires the amount instead of sending `amount_cents: undefined` on a blank amount, and offers a Full refund shortcut. Collections row actions get a 44px target on phone, primary action first, with the rest in a row menu. No refund/void API call, eligibility rule, or idempotency key changed.

## Deploy notes

Frontend-only changes. No new migrations, no new environment variables, no backend schema or endpoint changes.

## Risk / rollback

Low. Changes are additive/structural UI fixes (action list consolidation into a shared derivation, width-capped action column, Refund dialog clarity) with no data or schema impact and no change to the underlying refund/void/eligibility logic. Full backend gate (pytest, ruff check/format, lint-imports, mypy-baseline) and frontend gate (tsc, eslint, `next build --webpack`) pass on the branch. To roll back, revert this PR's merge commit.
