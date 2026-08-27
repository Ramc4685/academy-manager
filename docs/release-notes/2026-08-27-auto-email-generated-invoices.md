# auto-email-generated-invoices

PR: #TBD

## What changed
The monthly invoice-generation job now emails the invoices it creates. After
generating for an academy/period, the scheduler runs a send pass over that
period's invoices that still owe money and have never been delivered, reusing
the same `SendInvoice` path an admin's "Send" button uses (same pay link, same
bundling, same delivery tracking). Invoices on an actively-autopaying
enrollment are skipped so a parent is never asked to pay a bill that is also
being charged automatically. Counts land in the daily ops digest as
`invoices_emailed`, `invoice_emails_failed`, and
`invoice_emails_skipped_autopay`.

Before this, generation created invoices and sent nothing — non-autopay
parents were billed into the void unless an admin clicked Send on each one.

## Deploy notes
Migration `0152_invoice_delivery_period_index` adds an index on
`invoices (academy_id, period, delivery_status, created_at)`. It runs
automatically on boot via `run_migrations_on_boot`; no manual step.

Emails only go out where invoice email is already configured
(`email_delivery_enabled` + `resend_api_key`); without it the pass runs and
sends nothing, exactly as the admin Send button does today.

## Risk / rollback
The risk is sending email that was previously never sent. It is bounded by
`delivery_status`: only invoices that were never successfully delivered are
selected, so a re-run, catch-up run, or lease handover cannot email a parent
twice, and a pass is capped at 500 invoices per academy per tick. A failing
send pass cannot affect invoice generation — generation is recorded first and
send failures are swallowed and counted. Revert the PR to return to
generation-without-sending; the added index is harmless if left in place.
