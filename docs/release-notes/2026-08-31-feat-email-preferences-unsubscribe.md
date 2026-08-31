# email-preferences-unsubscribe

PR: #605

## What changed
Admin campaigns and both daily digests were bulk mail with no opt-out and no
per-recipient preference anywhere in the codebase — `grep -rni "unsubscribe|opt_out"
backend/v2` on main returned nothing. The only toggle was per-academy digest
on/off, which an admin controls and a parent cannot. CAN-SPAM/CASL require a
working opt-out in commercial email.

The gate is one seam, not a check per send loop. Every real send path is fed by
a port built in `composition/digests._build_email_sender` (an AST tripwire
enforces that single construction site), so `GatedEmailSendPort` decorates it
there and consults send-time `RecipientGate`s once per recipient.
`MongoEmailPreferenceGate` plugs into `preferences=`; the bounce suppression
list from #556 plugs into `suppressions=` on the adjacent line. A new bulk path
inherits the gate for free.

`EmailSendPort.send` grows `category=`, defaulting to TRANSACTIONAL. That
default is the safety property, not a convenience: the five transactional
adapters (invoice, dunning notice, login invite, dues reminder, add-card
reminder) are untouched by this change and therefore uncategorised, and the
preference gate returns ALLOW for TRANSACTIONAL before it reads the database.
`EmailPreferences` has no transactional field, and both request models forbid
extra keys, so a client sending `transactional` gets a 422 rather than silent
success. A family that could suppress its own invoice would be a billing
incident, not a preference.

A blocked send returns `SendOutcome(suppressed=True)` with its reason. The
campaign loop records that in the delivery log rather than dropping it — an
admin must be able to see why someone in the audience got nothing. Both digest
loops mark it failed with `retryable=False`, which is load-bearing: a FAILED row
with attempts remaining is re-claimed by the next hourly tick, so a retryable
unsubscribe would rebuild the plan and re-hit the same gate three times a day
forever.

The link is a stateless HMAC over `(academy_id, user_id)`. A stored one-time
token is the wrong tool — `IssueMagicLink` keeps only a SHA-256 and returns the
raw value once, so it cannot be regenerated for tomorrow's digest, and a
six-month-old email must still unsubscribe. Mutation is POST-only, for the
reason `magic_link_routes` already documents: mail scanners issue GET
prefetches, and a GET that mutated preferences would let a corporate scanner
unsubscribe families automatically. The URL is built on the academy's own
subdomain via `academy_frontend_url`, exactly like the portal and magic links in
the same digest, because TenantResolver (ADR-0007) reads the tenant from the
host's first label; the route then refuses an unresolved tenant in SaaS mode, so
the cross-tenant check is live on the host the emailed link actually uses.
Preferences are tenant-scoped — unsubscribing from one academy must not silence
a sibling enrolled at another. (#556's suppression list is deliberately the
opposite: a dead mailbox is a fact about the shared sender domain.)

`frontend/app/(marketing)/unsubscribe/page.tsx` is the login-less landing page:
preview the current choices with a POST, wait for a click, then confirm. Nothing
mutates on load. The ops digest is left ungated on purpose — its recipient is
`user_id="ops-alert"` with no academy in scope, and it is the channel that
reports that email is broken.

## Deploy notes
Merge this before #556: this branch carries the shared seam, and #556 is then a
pure addition plus one composition line.

Run migration `0157_email_preferences.py` before the first unsubscribe click. It
creates the unique `(academy_id, user_id)` index that makes the preference write
an upsert; without it, two concurrent clicks can create two rows.

Set `V2_UNSUBSCRIBE_TOKEN_SECRET` (or legacy `UNSUBSCRIBE_TOKEN_SECRET`) in
staging and prod, and only after this PR's frontend page is live. Until the
secret is set, nothing is signed: the footer renders a plain "email preferences"
sentence instead of a link and both endpoints 404. This is fail-closed by
design, but it also means the CAN-SPAM link is NOT live until the secret is
deployed. Generate a fresh random value — do not reuse another secret, and
treat it as long-lived: rotating it invalidates every unsubscribe link in every
email already sent.

Nothing changes for any recipient until someone actually opts out. An absent
`email_preferences` document means opted in, and no rows are back-filled.

Two things to watch on the first run after deploy. The admin campaign delivery
log will start showing FAILED rows with reason `unsubscribed:campaign` — these
are intentional records, not delivery failures, so a dashboard that alerts on
campaign `failed_count` needs to learn the difference. And digest `DigestSend`
rows blocked by a preference are written `retryable=False`, so they are excluded
from the ops digest's "lost digests" count by design.

Not done, and named rather than silently skipped: `List-Unsubscribe` /
`List-Unsubscribe-Post` (RFC 8058) headers — `EmailSendPort.send` has no
`headers` parameter, and Gmail/Yahoo bulk-sender rules want these, so it is
worth a follow-up. Firebase-sent password-reset and email-verification messages
never pass through `EmailSendPort` and cannot be gated by this seam at all.
There is no coach-facing or admin-facing preferences UI: a coach can opt out and
back in through the emailed link, but cannot reach it without an email in hand.

## Risk / rollback
Moderate, and asymmetric: the risk is not that mail stops but that it does not.
The gate is deliberately fail-open on a store outage (#435's lesson: email that
fails quietly stays broken for weeks), so if Mongo is unreachable
`MongoEmailPreferenceGate` logs `email_preference_gate_unavailable` and returns
ALLOW. A sustained outage would therefore let campaign mail reach opted-out
recipients, and nothing currently alerts on that log line — wiring it into the
ops digest is worth doing.

Transactional email carries the lowest risk in the change: the five transactional
adapters are not touched by this diff, so they remain uncategorised and are
allowed before the gate reads the database. Suppressing an invoice is not
reachable through any input, including a request that explicitly asks for it.

Rollback is a straight revert. The `email_preferences` collection is written
only when a recipient makes a choice, so reverting simply stops consulting it —
no data is orphaned or corrupted, and re-applying picks the same rows back up.
The one non-revertible consequence is social rather than technical: any
unsubscribe link already delivered stops working when the code is reverted, and
recipients who opted out would start receiving campaigns again. Prefer fixing
forward over reverting once the secret is live.

Preference is keyed on `user_id`, not email address, so a person holding two
user records in the same academy would have to unsubscribe twice; the
`(academy_id, email)` index exists to make an email-based sweep possible later.
The repo and gate are covered by `mongomock_motor`, which does not enforce
unique indexes, so the concurrent-double-click convergence is asserted by row
count rather than a real duplicate-key race — untested against a real MongoDB.
