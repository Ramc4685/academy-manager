# fix-registration-verification-email-from-our-domain

PR: #625

## What changed
Public parent self-registration now sends its "verify your email" message from
**our own Resend domain**, server-side, instead of Firebase's client-side
`sendEmailVerification`.

Firebase's client SDK delivers from its shared, unbranded mailer
(`noreply@<project>.firebaseapp.com`), which was **confirmed landing in Gmail
spam in production** — a parent who never finds the mail can never verify, and
never finishes enrolling. Invoice mail sent through our own Resend domain
delivers fine, so the send moves onto that domain, mirroring
`send_login_invite.py`, which already does exactly this for admin-created
accounts.

- `firebase_admin_adapter.py` gains `generate_email_verification_link(email)`
  (Admin SDK), so we mint the same Firebase link Firebase would have mailed.
- New use case
  `identity/application/use_cases/send_registration_verification_email.py`
  verifies the caller's ID token, generates the link, and sends a branded body.
- New route `POST /api/v2/register/parent/verification-email` (204), registered
  in `_PUBLIC_WRITE_PATHS` for the public-write IP rate limit. An interface test
  asserts that path string against the router's real mounted path, since a typo
  there would silently leave the endpoint unlimited.
- Frontend calls the new endpoint (`lib/api/registration.ts`);
  `lib/auth/firebase.ts` no longer imports `sendEmailVerification` and exposes
  `verificationRequestToken`, which resolves to a token **or throws** — it can
  never resolve nullish, because the caller's only failure signal is an
  exception.

### Abuse controls (the point of the design, not a detail)
The endpoint is unauthenticated apart from a Firebase ID token, and **anyone can
mint a Firebase account for an address they do not own** using the public web
API key. So the recipient address is attacker-chosen — and after this change,
every message spends the reputation of the domain our *invoices* go out on.
Before it, the abuse burned Firebase's shared reputation instead.

The IP rate limit cannot fix this: a mail bomb aimed at one victim needs a
*recipient*-side limit. New `verification_email_cooldowns` (migration `0163`,
`purge_at` TTL) enforces, per address: a 5-minute cooldown **and** a maximum of
5 sends per rolling 24h. Mongo rather than an in-process dict because the API
runs on several machines and restarts on deploy — an in-memory counter is both
per-machine and erased on deploy. This follows the shape of the existing
`login_attempts` / `idempotency_keys` / `parent_magic_links` throttles rather
than introducing Redis for one counter. The claim is a single conditional upsert
whose "denied" answer arrives as `DuplicateKeyError`, so it is atomic across
machines.

The budget is keyed on a normalised **mailbox identity**, not the raw string.
Sub-addressing (`victim+1@`, `victim+2@`) and Gmail's dot-insensitivity
(`v.i.c.t.i.m@`, `@googlemail.com`) all reach one inbox while producing distinct
Firebase accounts an attacker can mint per alias — so a raw-string key would
have made the cap 5 *per alias*, effectively unbounded at one victim, defeating
the only recipient-side control here. Normalisation applies to the key only; the
address actually mailed is always the one on the verified token. Dots are
stripped for Gmail alone, since they are significant almost everywhere else and
stripping them globally would merge two real parents' budgets.

Rows are keyed by a **hash** of that identity: anyone can create one for
an address they do not own, and the collection must not become an
unauthenticated log of every email typed at us. Exhausting the budget returns
429 and generates no Firebase link and no send.

### Failures are now honest
- `_build_email_sender` falls back to `StubEmailSendPort`, which reports
  `ok=True`, unless `email_delivery_enabled` **and** `resend_api_key` **and**
  `env in {staging, prod}` all line up. For digests that is correct. For a
  message a parent is watching it is a lie: a mistyped `RESEND_API_KEY` in prod
  would show every parent "Verification email sent", send nothing, and log
  nothing. `build_user_facing_invite_sender` now swaps a stub port for
  `UndeliverableInviteEmailAdapter` in a real-email environment — it logs at
  ERROR and reports failure, so the parent sees "could not send, try again" and
  the misconfiguration surfaces on the first attempt. Non-real environments keep
  the stub's silent success, so local and CI runs still mail nobody.
- The 502 now returns a fixed message; the underlying Firebase/Mongo text (which
  can name collections, hosts and provider error codes) is logged instead of
  being handed to an unauthenticated caller.
- Verifier failures that carry an HTTP status — a Firebase outage surfacing as
  500/503, or a 403 — are re-raised untouched rather than collapsing into 401,
  so a known outage is not reported to the parent as "your login is invalid".
  Note the limit: a *transport* failure (connection reset, socket timeout) has
  no status and still maps to 401. That is pre-existing behaviour, unchanged
  here and tracked separately; what this PR does fix is the leak — the 401
  detail is now a fixed string, so the raw exception text (which can name
  internal hosts) no longer reaches an unauthenticated caller.

## Deploy notes
Migration `0163` creates the `purge_at` TTL index on
`verification_email_cooldowns`; it runs at boot and needs no manual step.

**`_build_email_sender` keeps its name and its `(settings, db)` signature.** On
`main` it returns a suppression-gated `GatedEmailSendPort` (#556), and
`tests/structural/test_email_sender_construction.py` exists to catch a rename —
earlier work in progress had renamed it, which would have broken that gate.

The v2 settings this path depends on were confirmed present on Fly app
`courtmastr-academy-api` before merge: `V2_RESEND_API_KEY` and `V2_SENDER_EMAIL`
are deployed secrets, and `V2_EMAIL_DELIVERY_ENABLED = "true"` / `V2_ENV =
"prod"` are set in `backend/fly.toml`. All three conditions `_build_email_sender`
gates on therefore hold in prod, so the real Resend adapter — not the stub — is
what gets wired. If they are not, registration now **fails loudly** with
a 502 and an ERROR log rather than silently reporting success — that is the
intended behaviour, but it turns a previously invisible misconfiguration into a
visible registration outage.

## Risk / rollback
Medium. The delivery path for a user-facing message changes, and a new public
endpoint is added — though it sends only to the address inside a verified
Firebase token, never to one supplied in the request body (asserted by test).
The per-address budget is deliberately tight; if legitimate parents report being
throttled, raise `COOLDOWN` / `MAX_PER_DAY` in
`mongo_verification_email_cooldown.py` rather than removing the claim. Roll back
by reverting this PR: registration returns to Firebase's client-side sender, and
verification mail goes back to landing in spam. The `0163` index is harmless if
left in place.
