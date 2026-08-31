# bounce-suppression

PR: #TBD

## What changed
Nothing anywhere in v2 checked whether an address was worth mailing. Every
send — parent digest, coach digest, campaigns, invoices, dunning, login
invites, dues and add-card reminders — went straight to Resend, and a failure
was recorded per attempt and then re-attempted tomorrow. Repeatedly mailing
hard-bounced addresses is what gets a shared sender domain reputation-throttled
for every tenant on it.

Three things land (issue #556):

**A signed webhook.** `POST /api/v2/webhooks/resend` verifies the Svix
signature over the RAW request body before anything is written, then claims the
`svix-id` insert-first against a unique index — the same shape as the Stripe
webhook, so Resend's at-least-once retries can never apply a bounce twice. A
duplicate is a 200, an unrecognised event type is stored `ignored` and 200'd,
and only a bad signature is a 401. There is deliberately no empty-string
fallback on the signing secret: with no secret the route is not mounted at all
and the endpoint 404s. (`composition/admin.py` *does* fall back to `""` for the
Stripe Connect state secret — issue #547 — which means an unconfigured
deployment signs and verifies OAuth state with a guessable key. Not fixed here,
but it is why this slice does not copy the pattern.)

**Two collections, deliberately not tenant-scoped.** `email_suppressions` is
keyed on the address alone, following the `parent_magic_links` precedent: the
Resend sender domain is shared by every academy, so a hard bounce observed
while academy A was mailing must stop academy B from mailing the same address,
and the webhook has no tenant to scope to anyway. `email_provider_events` is
the idempotency log. Migration `0158` adds both plus their unique indexes.

**One gate, at one seam.** `GatedEmailSendPort` decorates whatever adapter
`digests._build_email_sender` produced, so "every send path checks the list" is
true by construction — no send loop grew a check, and `composition/email_adapters.py`
is untouched. The check is reason-aware: a `hard_bounce` blocks **every**
category including transactional (the mailbox does not exist; the invoice is
still in the parent portal), while a `complaint` or an admin `manual` entry
blocks digests and campaigns but still lets an invoice through. Soft bounces
and delivery delays never suppress at all — a full mailbox is not a dead
address. A blocked recipient comes back as `SendOutcome(ok=False,
suppressed=True, failed_reason="suppressed:hard_bounce")`, which the existing
loops already record, so it lands in the campaign delivery log and the digest
send log rather than vanishing. A Mongo outage in the gate returns ALLOW and
logs: a gate that fails closed on a blip would stop every invoice in the system
(the #435 lesson).

The ops digest is the one path left ungated on purpose — its recipient is
`ops-alert`, not a tenant user, and it is the channel that reports that email
is broken.

Admins get `GET /api/v2/admin/communications/suppressions` and a
`POST .../{email}/release` escape hatch. A release is not permanent: the next
bounce for that address re-suppresses it, and a reason can escalate
(complaint → hard_bounce) but never downgrade.

One regression this introduces and closes in the same commit:
`composition/admin.py` decided whether the local/test "email delivery is not
enabled" safety block applied by asking `isinstance(sender, StubEmailSendPort)`.
Once the sender is a decorator, that is False in *every* environment. The
check now goes through `digests.is_real_email_sender`, and
`v2/tests/composition/test_digest_email_env_gate.py` — which would otherwise
have become a tripwire that can never fire — unwraps too.

## Deploy notes
**Set `RESEND_WEBHOOK_SECRET` (or `V2_RESEND_WEBHOOK_SECRET`) before this is
useful.** Without it the route 404s and no bounce is ever ingested; the
suppression gate still runs but the list stays empty, so behaviour is identical
to today. That is the intended fail-closed default, not a broken deploy.

Then add the endpoint in the Resend dashboard: `POST https://<host>/api/v2/webhooks/resend`,
subscribed to `email.bounced`, `email.complained` and (optionally, for the
audit trail only) `email.delivery_delayed`. Resend issues the `whsec_...`
secret when the endpoint is created — that is the value the env var takes.

Migration `0158_email_suppressions` runs at boot and only creates indexes on
two new collections; it touches no existing data. No backfill is performed:
`email_suppressions` starts empty, and historical bounces recorded as
`message_deliveries.failed_reason` text are NOT retro-imported. That is a
separate ops task if it is wanted.

`List-Unsubscribe` / RFC 8058 headers are out of scope — `EmailSendPort.send`
has no `headers` parameter. Firebase-sent password-reset and verification mail
never passes through `EmailSendPort` and is not gated by any of this.

## Risk / rollback
Moderate, and concentrated in one place: every send now passes through a
decorator that does one indexed `find_one` on `email_suppressions` before
delegating. With an empty list nothing is ever blocked, so the blast radius on
day one is one extra point-read per recipient.

The sharp edge is the reason taxonomy. A `hard_bounce` stops transactional mail
— that is intended, but it means a misclassified bounce can stop a family's
invoices. The classifier only escalates to `hard_bounce` when Resend does not
say `Transient`/`Undetermined`, and the admin release endpoint is the manual
remedy. If a wave of false suppressions ever appears, the fastest mitigation is
to unset `RESEND_WEBHOOK_SECRET` (stops new ingestion immediately) and release
the affected addresses; the gate itself can be disarmed by reverting the one
`GatedEmailSendPort(...)` wrap in `digests._build_email_sender`.

Rollback is a straight revert. The two new collections are additive and can be
left in place; nothing else reads them.
