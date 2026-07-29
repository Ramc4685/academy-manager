# whatsapp-dues-reminder-links

PR: #PENDING

## What changed
Dues reminder emails are easy for a parent to miss, so the admin "Dues
follow-up" page (`/admin/reports/dues`) now offers WhatsApp as a second,
higher-signal channel for chasing an outstanding balance. Each row gains a
"Send" link that opens WhatsApp with the reminder already typed into that
parent's chat; the admin presses send in WhatsApp itself.

These are free `wa.me` click-to-chat deep links, not the WhatsApp Business
API: nothing is sent automatically, so there is no per-conversation cost, no
Meta template approval, and no automated-sending terms violation. The
backend builds the whole link (`https://wa.me/<digits>?text=<encoded>`) so
the reminder copy lives in one place rather than being duplicated in the UI.

The message carries the **parent-portal payments link**, not a Stripe link —
the same `{academy_frontend_url}/parent/payments` URL the reminder email
already uses (via `academy_frontend_url()`, so it points at the academy's own
subdomain), with the same "log in to the parent portal to pay" fallback when
no frontend URL is configured. There is no Stripe hosted URL in the dues
path today; a direct Stripe pay link would need a per-parent checkout session
and is deliberately left as a follow-up.

New pure helper `backend/v2/shared/comms/whatsapp.py` holds the phone
normalisation and the plain-text twin of the email copy.
`list_dues_followup()` now also reads `phone` from the `users` doc it was
already fetching (no extra query) and resolves the pay link once per page,
not per row; the slug/pay-URL resolution it shares with `_DuesReminderSender`
was extracted into one `_parent_payments_link()` helper instead of two copies.

## Deploy notes
No migrations, no new env vars, no new routes. `DuesFollowupParentView` gains
two optional fields (`phone`, `whatsapp_url`), both defaulting to `null`, so
the response stays backward compatible. Parent phone numbers are stored as
free text: a bare 10-digit number is assumed to be US (+1), an explicit `+`
or `00` prefix is honoured as written, and anything that cannot be resolved
confidently yields no link at all (the row shows `-`) rather than risking a
chat with the wrong person. Email delivery is untouched. If academies expand
outside the US, the default country code should become a per-academy setting.

## Risk / rollback
Low, and read-only: the change adds two fields to one admin-only list
endpoint and one column to one admin page. It sends nothing itself — every
WhatsApp message still requires a human to press send inside WhatsApp — so
there is no new outbound-delivery path to misfire. New tests:
`backend/v2/tests/unit/test_whatsapp_link.py` (23 cases covering phone
normalisation, refusal to guess ambiguous numbers, message copy, and URL
encoding) plus two `list_dues_followup` cases in
`backend/v2/tests/unit/test_admin_composition_tenancy.py` (link built for a
parent with a phone; `null` for one without). Full backend suite green (2692
passed); frontend typecheck, lint, and build green. Adding a return
annotation to `list_dues_followup` also resolved 4 entries in
`backend/mypy-baseline.txt`, which is synced in this PR. Rollback = revert the
PR; the dues page returns to email-only.
