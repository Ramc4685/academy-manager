# checkout-hold-double-charge

PR: #490

## What changed
A parent who paid an invoice manually could be charged a second time by autopay.
Nothing marked an invoice "someone is paying this right now", and invoice status
only moves once the success webhook drains — a 60s tick, 25 events per academy,
backoff up to an hour. The hourly dunning tick read the still-open invoice and
fired an off-session charge under a fresh per-rung key, which Stripe's own
idempotency does not dedupe. An invoice now carries a checkout hold from the
moment its pay link is minted until the session completes, expires or fails, and
autopay stands off while that hold is live. Bundled balance links hold every
invoice behind them.

Separately, `stripe_not_configured` was being treated as a card decline: it
advanced the dunning ladder and eventually disabled a family's autopay even
though their card was never charged. It now parks like the other "we could not
ask" outcomes, so a misconfiguration on our side never spends a family's retry
budget.

## Deploy notes
None. No migrations, no new env vars, no config. Two nullable fields
(`checkout_hold_session_id`, `checkout_hold_started_at`) are added to the
`invoices` documents and default to null, so existing invoices load unchanged and
simply have no hold until their next pay link is minted.

## Risk / rollback
The failure direction is a delayed charge, not a wrong one: a hold that fails to
clear only defers autopay until the session's terminal webhook lands or the
90-minute backstop lapses, and the dunning ladder's rungs are days apart, so a
held invoice loses at most one tick and never a rung. Watch the
`checkout hold released invoice=… session=…` and `charge_autopay: parking
invoice=… — checkout session … still open` log lines, plus the dunning worker's
`parked` and `technical_failures` counters on the admin billing-health panel; a
`send_invoice: FAILED to hold invoice=…` line means that one invoice is briefly
double-chargeable again. Roll back by reverting the PR — holds already written
become inert fields and autopay resumes its previous behaviour immediately,
including the double-charge exposure this removes.
