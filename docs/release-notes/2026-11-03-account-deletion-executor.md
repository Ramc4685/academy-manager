# account-deletion-executor

PR: #1115

## What changed
Self-service account deletions are now carried out 14 days after the request (slice M5, part D3). Until now a request only locked the account.

- A new hourly job, `execute_account_deletions` (minute :50), picks up every request whose 14-day window has ended and erases the person's data in each academy they belonged to:
  - every live class is dropped with the "adjustment" outcome, so no credit or refund is created and any balance stays with the academy;
  - the children are anonymised: the name becomes "Student 4F2A", and date of birth, medical notes, emergency contact, notes and photo are removed. Attendance, progress and payroll history stay;
  - family contacts, notes, follow-ups, contact log, family details, the CRM lead and onboarding applications are deleted;
  - saved cards are detached at Stripe and forgotten locally; the Stripe customer is kept for refunds and disputes;
  - messages they wrote show "Deleted user", delivery rows lose the copied email, and email preferences are deleted;
  - the user record becomes "Deleted user" with an undeliverable placeholder email and no phone; magic links, login attempts and verification cooldowns are deleted;
  - the Firebase account is deleted last, and a `user.deletion_completed` audit row is written per academy.
- Invoices, payments, payouts and audit snapshots are kept unchanged under the 7-year retention.
- If another guardian on the family still has an active account in that academy, the children and family records are kept, and an ops alert asks an admin to re-home the family. The classes are still dropped, because billing belonged to the deleted parent.
- A failure on one account is recorded on its request (`last_error`, `attempts`) and retried after a back-off of 1 hour, doubling up to a day, so a stuck account never blocks the queue. Every step is safe to repeat, and other accounts carry on.
- The request row drops its email once the job completes.
- An academy that re-enables the account during the 14-day window cancels the deletion: the scheduled request is removed, and the job checks each request again just before erasing it.

## Deploy notes
No migration and no new secrets. The job runs on deploy, and in production it uses the live Stripe key to detach cards. To get a Sentry Crons check-in, add `execute_account_deletions` to `SENTRY_CRON_JOBS` (each monitor counts against the plan). Without it, the ops digest still flags the job as stale after 3 hours.

## Risk / rollback
High impact and irreversible per account once a request is due: the data is gone. Only requests made through D1, 14 days earlier, are touched. To stop the job, remove the deployed code or set a request back from `scheduled`. Requests that already completed cannot be restored. Not handled yet: open makeup requests, WhatsApp group membership, restricting waivers to owners, and send logs that hold an email (`invoice_contact_email_sends`, raw `email_provider_events`).
