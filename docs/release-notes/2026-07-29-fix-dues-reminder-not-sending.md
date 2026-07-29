# fix-dues-reminder-not-sending

PR: #379

## What changed
The admin "Dues follow-up" page's reminder-email action always returned
`blocked: true` with a "Local/test safety block" message, in every
environment including production — the handler was an unfinished stub that
never called the real email sender. `_DuesReminderSender` in
`backend/v2/composition/admin.py` now resolves each recipient through their
active parent membership (mirroring `InvoiceEmailAdapter`, not the raw
`list_dues_followup()` email join, which can be stale for a parent with
invoices in more than one academy) and sends through the same
`EmailSendPort` selection already used by invoice/dunning email. That
selection now also requires `settings.env` to be `staging`/`prod` (mirroring
the parent-digest sender's gate) on top of `EMAIL_DELIVERY_ENABLED` +
`RESEND_API_KEY`, so the stub sender's always-`ok=True` response can never
be reported as a real send in local/test, and a dev stack with inherited
prod-like flags can't hit Resend for real. Also gave the dues reminder,
invoice, and autopay-dunning emails the same branded header/CTA-button/
footer already used by the password-invite email (academy name pulled live
from academy settings).

Separately: `frontend_url` is a single deployment-wide setting, so every
academy's parent daily digest ("class reminder"), dues reminder, and
invoice checkout links pointed at the same generic host regardless of which
academy the email was for (e.g. `academy.courtmastr.com` instead of
`blno-academy.courtmastr.com`). Added `academy_frontend_url()` (a pure
helper in `backend/v2/shared/tenancy/academy_url.py`) that swaps the host's
first label for the academy's own `slug` — the same value TenantResolver
uses to resolve the tenant from a request's Host header — and wired it into
the digest's login/magic-link/portal/dues/absence links, the dues-reminder
pay link, and the invoice checkout success/cancel URLs.

## Deploy notes
No migrations or new env vars. Behavior in a given environment now depends
on the existing `EMAIL_DELIVERY_ENABLED` / `RESEND_API_KEY` / `APP_ENV`
settings for that deployment — confirm those are set correctly wherever
reminders should actually go out. Link correctness depends on each
academy's `slug` field being set (added by migration `0105_academy_slug`);
an academy without one falls back to the previous (generic) behavior rather
than breaking.

## Risk / rollback
Low: additive changes to two composition closures, one composition-layer
email-adapters module, and one new pure shared helper; `DuesReminderEmailAdapter`
is new, and `InvoiceEmailAdapter` gained one new constructor dependency
(`MongoAcademyRepository`, already instantiated in `compose_admin`). New
tests: `backend/v2/tests/contract/test_dues_reminders_send.py` (blocked-by-
default, real send in an approved env, membership-skip case) and
`backend/v2/tests/unit/test_academy_frontend_url.py` (host-rewrite edge
cases, including the apex-domain-corruption case the tests themselves
caught during review). Full backend suite green (2668 passed). Rollback =
revert the PR; the previous stub-blocked and generic-domain behavior
returns.
