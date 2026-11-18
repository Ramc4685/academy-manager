# Demo Academy

A fictional academy for App Store and Google Play reviewers, served at
`https://demo-academy.courtmastr.com` (slug `demo-academy`, academy id
`acad_demo_academy`). The iPhone and Android apps link to it from the login
page ("Explore the demo academy"). Everything in it is made up.

`backend/scripts/seed_demo_academy.py` creates it and puts it back to its seeded
state. It writes only the demo academy's documents, the four logins' `users`
rows and Firebase accounts, and an `email_suppressions` row per login. It
refuses to run if the slug or host already belongs to another academy.

## Logins

All four share one password. It is not stored in this repo: it is whatever was
typed at the last `--apply`.

| Email | Role |
| --- | --- |
| `demo.owner@example.com` | owner (owner + admin) |
| `demo.admin@example.com` | admin |
| `demo.coach@example.com` | coach |
| `demo.parent@example.com` | parent of Sam and Alex Demo |

## What it seeds

Two weekly classes taught by Demo Coach ("Junior Beginners" on Saturdays, a free
Wednesday clinic) with dated classes from four weeks back to four weeks ahead,
two students enrolled, attendance on past classes, and this month's tuition:
Sam's invoice paid in cash, Alex's open and due in two weeks.

Nothing can charge or email anyone: no card, Stripe customer, autopay or
connected account exists, and the four addresses are suppressed as
`hard_bounce`, so the send gate drops every email to them. The monthly invoice
run skips this month's tuition (the seeded invoices cover it) but will bill
next month's; that is harmless and the next re-run removes it.

## Run it on production

```sh
fly ssh console -a courtmastr-academy-api
python -m backend.scripts.seed_demo_academy           # dry run: prints what it would write
python -m backend.scripts.seed_demo_academy --apply   # prompts for the shared password
```

The machine already has `MONGO_URL`, `DB_NAME` and the Firebase credentials.
The password comes from the prompt (or `DEMO_PASSWORD`); it is never printed or
logged. Use at least 8 characters, and give the same one to the reviewers in
App Store Connect and the Play Console.

## Reset

Re-run `--apply` any time. It replaces every seeded document, deletes anything
else the demo academy has gained in those collections (invoices, payments,
attendance, memberships and so on), moves the class dates to around today and
resets the four passwords. If a reviewer deletes a demo account, re-running
recreates the Firebase account and restores its membership.
