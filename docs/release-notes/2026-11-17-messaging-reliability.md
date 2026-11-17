# messaging-reliability

PR: TBD

## What changed
Billing emails (invoice, dunning, autopay notice, receipt, payment reminders, add-card) now show the academy's name as the From display name and use its reply-to (or support email), like every other email already did. Every email sent from an outbox event carries a Resend `Idempotency-Key`, so a retried event no longer mails a family twice; a 409 on a reused key counts as already sent. Production now warns at boot and on `/api/v2/healthz` (`warnings`) when bounce ingestion or unsubscribe secrets are missing. New, all off by default: bounded send retry, a separate marketing sender for campaigns, RFC 8058 one-click `List-Unsubscribe` plus the academy postal address on campaigns, and a one-time sign-in link on the autopay-failed email button.

## Deploy notes
No migration. Optional env vars, all default to today's behaviour:
- `V2_EMAIL_SEND_MAX_RETRIES` (0-5): retries after a Resend 429, or a 5xx when the send has an idempotency key.
- `V2_MARKETING_SENDER_EMAIL`: From address for campaign mail; must be a Resend-verified domain.
- `V2_EMAIL_LIST_UNSUBSCRIBE_ENABLED=true`: campaign `List-Unsubscribe` headers (POST `/api/v2/unsubscribe/one-click`) and the academy `address` in the campaign footer. Needs `UNSUBSCRIBE_TOKEN_SECRET`.
- `V2_DUNNING_SIGNED_PAY_LINK_ENABLED=true`: the dunning button becomes a 72h single-use magic link to the pay page. A new magic link revokes the parent's earlier unused one, so the digest and dunning links supersede each other.
If prod lacks `RESEND_WEBHOOK_SECRET` or `UNSUBSCRIBE_TOKEN_SECRET`, expect a Sentry message on boot.

## Risk / rollback
The sender-identity change alters the From display name and adds a Reply-To on billing mail; the From address is unchanged. The idempotency header is sent only inside an outbox handler run. Roll back by reverting the PR; each optional feature turns off by unsetting its env var.
