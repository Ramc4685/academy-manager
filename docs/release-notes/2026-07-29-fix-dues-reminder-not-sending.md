# fix-dues-reminder-not-sending

PR: #379

## What changed
The admin "Dues follow-up" page's reminder-email action always returned
`blocked: true` with a "Local/test safety block" message, in every
environment including production — the handler was an unfinished stub that
never called the real email sender. `_DuesReminderSender` in
`backend/v2/composition/admin.py` now sends one reminder per parent through
the same `EmailSendPort` selection already used by invoice/dunning email
(Resend when `EMAIL_DELIVERY_ENABLED` + `RESEND_API_KEY` are set, the
in-memory stub otherwise), and reports real `sent`/`blocked` counts back to
the UI. Also gave the dues reminder, invoice, and autopay-dunning emails the
same branded header/CTA-button/footer already used by the password-invite
email (academy name pulled live from academy settings), so outbound mail
reads as one product instead of plain unstyled paragraphs.

## Deploy notes
No migrations or new env vars. Behavior in a given environment now depends
on the existing `EMAIL_DELIVERY_ENABLED` / `RESEND_API_KEY` settings for
that deployment — confirm those are set correctly wherever reminders should
actually go out.

## Risk / rollback
Low: additive change to one composition closure and one composition-layer
email-adapters module; `DuesReminderEmailAdapter` is new, and
`InvoiceEmailAdapter` gained one new constructor dependency
(`MongoAcademyRepository`, already instantiated in `compose_admin`). New
contract test `backend/v2/tests/contract/test_dues_reminders_send.py`
exercises the real composition wiring. Full backend suite green (2662
passed). Rollback = revert the PR; the previous stub behavior (always
blocked) returns.
