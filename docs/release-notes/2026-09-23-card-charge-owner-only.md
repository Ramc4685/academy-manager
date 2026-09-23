# Card charges are owner-only: both charge routes, the use case and the Family "Fix something" panel (#928)

PR: #TBD

## What changed

- **Routes.** `POST /api/v2/admin/billing/invoices/{invoice_id}/charge-autopay` and `POST /api/v2/admin/billing/setup/{parent_id}/charge` now use `require_owner()` instead of `require_persona("admin")`. They are listed in `OWNER_ONLY_ROUTE_PATHS` (`backend/v2/interfaces/admin/owner_gate.py`). A non-owner admin gets the same `404` as every other owner-only route. This follows the 2026-09-22 staff-tier decision (roadmap section 6 item 2): money-moving actions are owner-only, billing staff record payments, and front desk sees an owes-money flag.
- **Use case.** `charge_invoice_as_admin` (`backend/v2/contexts/billing/application/charge_admin_invoice.py`) is the one audited path both routes use. It now takes a required `actor_roles` argument and raises `ChargeRequiresOwner` before it touches anything unless the actor holds `owner`. That includes the idempotency plan, a cached result, the audit entry and Stripe. A caller that skips the route still cannot charge a card, and a caller that leaves out the roles fails closed. The two `compose_admin` closures (`charge_invoice_as_admin_action`, `charge_billing_setup_balance`) pass the roles through. Both routes map `ChargeRequiresOwner` to `404`.
- **Billing tab.** `charge_card` joins `family_billing.OWNER_ONLY_ACTIONS`, so the Family billing view no longer offers it to a non-owner. `record_payment` stays open to billing staff.
- **Frontend.** In `FixSomethingPanel.tsx`, "Charge card now" is now `ownerOnly`, like void, refund and one-time discount. Every action in that panel moves money, so a plain admin no longer sees the panel at all. The check lives in the new exported `fixItemsFor(isOwner)`, which reads the existing `useIsOwner()` signal.
- **Tests.** The strict xfails in `structural/test_money_route_staff_tiers.py` are gone. Both charge routes are now asserted with the other money-moving routes, and `charge_card` is asserted in `OWNER_ONLY_ACTIONS`. New tests:
  - Interface: `interface/test_admin_card_charge_owner_gate.py` (the owner is allowed, a non-owner admin gets `404` and the use case is never called, and a refusal from the use case is a `404`, not a `500`).
  - Unit: `unit/test_charge_admin_invoice.py` (a non-owner is refused before anything is written, cannot replay a cached charge, and missing roles fail).
  - Real mongod: `contract/test_card_charge_owner_gate.py` (for both entry points, the owner charges; a non-owner admin moves nothing, with no PaymentIntent, idempotency key, audit entry or ledger payment; and the owner of another academy is refused, with academy A's invoice untouched).
  - Frontend: vitest `FixSomethingPanel.test.ts`. The Playwright `admin-family-billing.spec.ts` non-owner case now expects no Fix panel.

## Deploy notes

- No migration.
- No config or env changes. This is a backend and frontend deploy only.
- Non-owner admins lose the "Charge card now" action as soon as this deploys. Owners keep it. Tell academy staff before the release.

## Risk / rollback

- Behavior change: admins without `owner` could charge a family's saved card before this change and now cannot. The 2026-09-22 owner decision asks for this. Admin memberships migrated before the role split (0165) also hold `owner`, so those admins are unaffected.
- The internal signature changed: `charge_invoice_as_admin`, `charge_invoice_as_admin_action` and `charge_billing_setup_balance` now require `actor_roles`. Every in-repo caller has been updated. Autopay and dunning charges use `charge_invoice_via_autopay` directly, and this PR does not touch them.
- Rollback: revert the PR. There is no data or schema change to undo.
