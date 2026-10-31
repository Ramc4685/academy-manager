# Billing and front desk staff tiers (backend)

PR: #957

## What changed
Adds the `billing` and `front_desk` staff roles (#553, owner decision 2026-09-22). Billing staff can record a manual payment and mark a payment paid; front desk gets no money write. Refunds, voids, discounts, adjustments, fees and card charges stay owner-only. Existing admin and owner accounts work exactly as before. Only the owner can grant or revoke the new roles. Backend only: the Staff page and the CRM "owes money" redaction come in later slices. Also registers the CRM `contact_id` route parameter in the two-tenant isolation test, which went red on main after #950.

## Deploy notes
No migration id (none added). No owner steps are needed to deploy. After deploy the owner may grant the new roles. The `academy_memberships.roles` validator already accepts any string (verified on a real mongod). No env vars.

## Risk / rollback
If wrong, a billing member could reach record-payment/mark-paid (the only routes opened to the new tier) or be refused them. No existing role's access changed. Roll back by reverting the PR; any membership already granted `billing`/`front_desk` then fails to load and should have that role removed first.
