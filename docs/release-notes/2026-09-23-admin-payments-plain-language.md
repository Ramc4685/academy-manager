# Admin payments: plain-language payment notes and one Billing Health title (UI-5)

## What changed
- All invoices row notes in Admin > Payments now use plain sentences instead of backend codes such as "Stripe linked, app ledger pending", "orphan charge", "missing allocation" or raw decline codes. Notes that need someone to act point to Billing Health. Healthy synced rows show no note.
- Row titles say "Monthly tuition" because the Period column already shows the month.
- Billing Health shows its title once (the page's own h1 was removed; the admin topbar shows the title).
- Test only: the two-tenant isolation test now registers the `contact_id` route parameter that the family contacts work (#950) added.

## Deploy notes
- Frontend copy only. No migration, no new environment variables, no owner steps.

## Risk / rollback
- Low risk: only display strings changed; no API, data or billing logic changed.
- Rollback: revert this PR and redeploy the frontend.

PR: #955
