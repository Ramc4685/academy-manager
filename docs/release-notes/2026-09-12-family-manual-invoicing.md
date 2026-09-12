# Manual invoicing on the family billing page

PR: #722

## What changed

- The admin family billing page can create a draft invoice for a student/period, add charges to a draft, and send or void drafts. Sending a draft with no charges is refused.
- A per-enrollment "Bill this month" shortcut creates a draft with the tuition line at the session price and the enrollment's active recurring discount as its own line, matching the monthly generator's pricing.
- New endpoint `POST /admin/enrollments/{enrollment_id}/invoices/bill-period` (admin persona). It refuses a $0 session price, an existing non-void invoice for that enrollment and period, and concurrent duplicates; a voided draft can be re-billed.
- The invoice dialogs previously stranded under the student page move to `frontend/components/admin/billing`.

## Deploy notes

- No migration and no new environment variables.
- Frontend and backend ship together; the family page calls the new bill-period route.

## Risk / rollback

- Additive: existing invoice flows and the monthly generator are unchanged. Drafts left unsent for an enrollment/period still count as "already invoiced" for that month's generator run, so send or void drafts promptly.
- Rollback: revert the PR. Draft invoices created through the new controls remain valid ledger rows.
