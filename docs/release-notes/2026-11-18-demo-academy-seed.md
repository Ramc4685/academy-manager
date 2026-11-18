# demo-academy-seed

PR: #0

## What changed
A new script, `python -m backend.scripts.seed_demo_academy`, creates the fictional Demo Academy at `demo-academy.courtmastr.com` for App Store and Play reviewers: four logins (owner, admin, coach, parent) sharing one password typed at run time, two classes, two students, attendance and two small invoices (one paid, one open). A dry run is the default; `--apply` writes. Re-running resets the demo, including a deleted demo account. Runbook: `docs/runbooks/demo-academy.md`.

## Deploy notes
- No migration. Nothing runs on deploy; run the script by hand after this deploys (dry run first, then `--apply`), on `courtmastr-academy-api` via `fly ssh console`.
- Needs #1212 deployed (multi-academy mode and the demo host in CORS).
- If the demo academy was already created at `/platform/tenants`, the script refuses to run; that academy has a different id.

## Risk / rollback
- Risk: low. Every write names `acad_demo_academy`, plus the four `@example.com` users, their Firebase accounts and their `email_suppressions` rows. BLNO is never written.
- The demo cannot charge (no card, Stripe customer, autopay or connected account) or send email (its addresses are suppressed as hard bounces).
- Rollback: revert the PR. To remove the demo data, delete documents with `academy_id: "acad_demo_academy"`, the four users, their Firebase accounts and suppression rows.
