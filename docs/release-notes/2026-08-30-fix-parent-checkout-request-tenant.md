# parent-checkout-request-tenant

PR: #575

## What changed
`compose_parent` froze a single boot-time `academy_id` into the checkout-path
billing use cases (`StartCheckout`, `StartSubscriptionCheckout`,
`GetCheckoutStatus`) while `settings.tenancy_mode` defaults to
`multi_academy`. Had a second academy ever been served, a parent of academy B
starting checkout would have minted a payment record and Stripe metadata
stamped with academy A's id — visible in A's admin payment feed and invisible
to B's reconciliation — and B's autopay setup completion via the status poll
would have failed on the academy-mismatch guard. The three use cases now
accept a request-time academy provider and resolve it at execute time;
`compose_parent` wires the same `request_academy_id` helper the rest of the
file already uses (ContextVar tenant, fail-closed in `multi_academy` mode,
boot fallback only in `single_academy` mode so outbox/scheduler callers are
unchanged). Webhook processing stays per-academy by design: the scheduler
composes one `HandleWebhookEvent` per academy and the handler already
quarantines cross-academy events.

## Deploy notes
None beyond the normal deploy. No migration, no new configuration. In today's
single-academy launch mode every path resolves to the same academy it did
before.

## Risk / rollback
Behaviour is identical in single-academy operation; the change only alters
which academy id is stamped when a request tenant differs from the boot
tenant, which cannot happen under the current launch guard. The one new
failure mode is deliberate: in `multi_academy` mode a checkout call with no
resolved request tenant now raises (fail closed) instead of silently stamping
the boot academy. Roll back by reverting the merge commit — the use cases
still accept a plain string academy id, so older wiring composes unchanged.
