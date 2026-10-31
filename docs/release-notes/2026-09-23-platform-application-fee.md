# Per-academy platform application fee (roadmap L9b)

PR: #958

## What changed

- Stripe's `application_fee_amount` on destination charges was hard-coded to 0 in three places. It now comes from a per-academy setting, `billing_settings.application_fee_bps` (basis points, **default 0**). The three charge paths are the registration checkout, the invoice and balance pay links, and off-session autopay. The fee is rounded down to the cent and can never exceed the charge. The gateway (real and fake) refuses a negative fee, a fee above the charge, or a fee on a platform-direct charge before it calls Stripe.
- **Platform admin only.** New `GET/PUT /api/v2/platform/academies/{academy_id}/application-fee` (from 0 to 1,000 bps, which is 10%). Every change writes an `application_fee_changed` entry to the academy's billing audit log. The academy-side settings write never persists the field, even from a stale read. Academy admins have no route to it, and platform support gets 404.
- A "Platform application fee" card on `/platform/tenants/[academyId]`, shown to platform admins, displays the fee and lets them change it.
- When a non-zero fee is set, Stripe idempotency keys for those charges get a `:fee<cents>` suffix, so a fee change inside Stripe's idempotency window does not turn a retry into a parameter-mismatch error. At 0 the keys and requests are byte-identical to before.

## Deploy notes

- No migration. The field is optional in the 0136 validator, and a missing field reads as 0.
- No env or config changes. After deploy every academy is still at 0%, and nothing changes until a platform admin sets a fee.
- Owner steps: none to deploy. To charge a fee later, a platform admin sets it per academy on the tenant page. Also carries the one-line `contact_id` isolation-test fix for #950.

## Risk / rollback

- If billing settings cannot be read at charge time, the charge goes through with **no** fee (logged as an error) rather than blocking the parent.
- Rollback: revert the PR. A stored `application_fee_bps` is then ignored, and charges go back to a literal 0.
