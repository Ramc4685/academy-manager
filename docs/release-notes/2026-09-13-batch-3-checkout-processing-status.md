# batch-3: checkout processing status

PR: #0

## What changed

- Fixes #635 — parents returning from Stripe Checkout no longer see a paid
  invoice sitting at PENDING while the 60s webhook-drain scheduler tick
  catches up. Every invoice/balance checkout now returns a
  `checkout_session_id`, the settlement poll runs on any checkout return
  (not just autopay opt-ins), and `GetCheckoutStatus` derives a
  non-persisted "processing" status (plus the invoice ids in flight) from
  the completed Stripe session so the portal can show "Payment received —
  updating your balance" and badge those rows, falling back to "Confirmed
  by Stripe" copy after the ~2 minute cap.
- Follow-up review fix: the terminal `PaymentStatus` set used by the poll
  only listed subscription/ACH states plus "succeeded", so an unsuccessful
  payment ("failed", "expired", "refunded", "partially_refunded",
  "partially_paid", "waived") kept polling for the full ~2 minutes and then
  showed the reassuring amber banner. The full terminal set is now
  recognized, and unsuccessful outcomes get their own red banner instead of
  the "no need to pay again" copy.

## Deploy notes

No migrations. No new env vars or manual steps — purely application-level
changes to the parent billing use case and the parent payments page.

## Risk / rollback

Risk is limited to the parent payments page's post-checkout status banner
and the `GetCheckoutStatus`/checkout-response shape used by that page; no
persisted data model changed. If this regresses, revert this PR (or the
merge commit once merged) — the prior behavior (poll only on autopay
opt-in, PENDING shown until the webhook lands) will return.
