# checkout-session-orphan

PR: #596

## What changed
`start_checkout_for_application` minted the Stripe Checkout Session and wrote
the pending Payment before calling the `CHECKOUT_PENDING` transition, whose
first act is `_assert_child_not_enrolled` — ahead of its own CAS and ahead of
any retirement. Nothing wrapped that window, so any raise in it left a payable
Stripe session and a pending `ledger_payments` row that no application
referenced. A parent who paid that session had the money taken silently: the
webhook resolves the payment by `checkout_session_id` and marks it succeeded,
then `execute_for_payment` looks the application up by `payment_id`, finds
`None` and returns without a log. Reachable via an ambiguous same-name
registration match, an enrollment appearing after the last child-profile patch,
TOCTOU on the composition's status guard, or any Mongo error.

Minting the session after the transition is not available — the transition
consumes both ids to stamp the claim — so the window is now wrapped: any raise
retires the just-minted attempt through the same `_StripeCheckoutAttemptRetirement`
instance the transition itself uses, then re-raises the original exception
unchanged. A failure inside the compensation is logged and never masks the
original error.

Also closes a vacuous test: neutering the `DRAFT -> CHECKOUT_PENDING` status
write in `MongoApplicationRepository` previously left all 62 tests in the area
green. A new test drives the entry claim from DRAFT through the real repository
and asserts the status actually moved.

## Deploy notes
None. No migration, no new environment configuration, no new collection or
index. Behaviour on the success path is byte-identical — the parent receives the
same `StartCheckoutResult`; only the failure path changed, and it raises the
same exceptions it raised before. Stripe sessions orphaned by this bug BEFORE
this deploy are not swept by this change and remain payable until they expire on
Stripe's own timer; a re-cancel audit of pending `ledger_payments` rows whose
`payment_id` no application references would find them.

## Risk / rollback
Low. The change is confined to one composition function: a try/except around an
existing call, plus tests. The compensation reuses machinery already in
production on the re-stamp path. Worst case it retires a checkout attempt the
parent could never have paid anyway (the caller never receives `redirect_url`
when the transition raises), and the application is left in a state the next
start re-stamps. Rollback is a straight revert; no data migration to unwind.
