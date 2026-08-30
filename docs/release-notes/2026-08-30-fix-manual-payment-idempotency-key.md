# manual-payment-idempotency-key

PR: #573

## What changed
The admin record-payment endpoint derived its idempotency key entirely from
the request payload (`invoice_id:amount:method:reference:notes`) with a 7-day
TTL, so a second legitimate identical manual payment — a parent paying the
same cash amount toward the same invoice twice in a week with blank
reference/notes — silently replayed the cached first result: the API returned
201 with a stale balance and the second payment was never recorded, with no
error and no audit entry (issue #511).

The route now accepts a client `Idempotency-Key` header (already in the CORS
allow-list) and keys the idempotency store on it, scoped to the invoice:
retries of the same submission still replay safely, while a legitimate repeat
payment mints a new key and records. When no header is sent, the
payload-derived key remains as a fallback, but a hit on it now returns a 409
"possible duplicate — resend with an Idempotency-Key header to confirm"
instead of silently replaying the first result. Both admin UIs
(`recordAdminInvoicePayment` in `frontend/lib/api/admin.ts`) mint a fresh
`crypto.randomUUID()` key per submission.

## Deploy notes
No migration; the existing `idempotency_keys` collection, unique index, and
7-day TTL are reused with a new `manual_payment:{invoice_id}:key:{key}` key
shape for keyed submissions. Old payload-derived keys already in the store
remain valid for the keyless 409 fallback until their TTL lapses. Frontend and
backend can deploy in either order: an old frontend hitting the new backend
gets the 409-on-duplicate behaviour (a real error instead of a silent swallow),
and a new frontend hitting the old backend sends a header the old route
ignores.

## Risk / rollback
Behaviour change for API callers that relied on the silent replay: a
payload-identical keyless repeat inside the TTL now gets 409 instead of a
replayed 201. That is the intended fix — the replay was masking unrecorded
cash — and the 409 detail tells the caller how to proceed. The known residual
gap is unchanged from before: the store's get/put pair is non-atomic, so two
truly concurrent identical submissions can still both record (over-recording,
which is visible and refundable, unlike the silent swallow). Roll back by
reverting the merge commit; stored keyed idempotency entries simply age out
via the TTL.
