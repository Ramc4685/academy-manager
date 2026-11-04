# Money settings are owner-only (Settings overhaul Phase 1 PR 5)

PR: #1002

## What changed

- Only the academy owner can now change anything that sets what families are charged or when a billing month starts. Admins without the `owner` role keep everything else.
- **Price list (Settings -> Session types):** create, edit, archive and reactivate are owner-only (`require_owner`, 404 for a plain admin, like every other owner-only route). Listing stays admin. Admins see the list with an "Owner only" hint in place of the buttons.
- **Class monthly fee:** `PATCH /api/v2/admin/sessions/{id}` refuses a plain admin with 403 "Only the academy owner can change prices and fees." only when `amount_cents` changes. A full-form resubmit with the fee untouched still saves. `POST /api/v2/admin/sessions`: a plain admin may create a class only unpriced (fee absent or null). There is no academy-wide default fee, so unpriced is what every new class starts from; the owner then sets the price. Any fee, including an explicit 0, is refused with the same 403. The fee box is disabled with an "Owner only" note in all three class forms for a plain admin.
- **Academy timezone and currency:** `PATCH /api/v2/admin/academy` refuses a plain admin with 403 ("Only the academy owner can change the timezone." / "...the currency.") only when the value changes (a currency equal ignoring case counts as unchanged and is not rewritten). The other academy fields stay admin. Both selects are disabled with an "Owner only" note for a plain admin. The setup checklist marks the Session types step owner-only and the Academy details step says the owner sets the timezone.
- **Self-service tab** is no longer a second place to change the late-cancellation fee and notice. `PUT /api/v2/admin/self-service/policy` answers 422 (pointing to Billing rules) when either is sent with a changed value, for owners too; an unchanged value from an old client still passes. The panel shows the current terms as one line with a link to Billing rules instead of the two inputs. Billing rules (owner-only) is their one write path.
- **Audit:** an owner's change to a class fee or the academy timezone appends one entry to the existing `billing_audit_log` (new actions `session_fee_changed` and `academy_timezone_changed`), next to the `billing_rules_changed` entries. Best effort: an audit failure is logged, never turned into a 500 after the write landed.
- Already owner-only before this PR and unchanged: Billing rules (late fee, grace, billing day, due days, cancellation terms), `/academy/fees`, invoice schedule, billing products, per-enrollment price override and ad-hoc fee, tuition discounts, payment discounts. The ACH discount has no tenant write path.

## Deploy notes

- No migration. No stored data changes; nothing is backfilled.
- Every admin that existed before the owner/admin split holds `owner` (migration 0165), so BLNO's current staff see no change. Only admins invited later without `owner` lose the ability to change prices, fees, timezone and currency.

## Risk / rollback

- Main risk: an ops-only admin who used to set class fees or edit session types now has to ask the owner. That is the intended policy. A class an admin creates is unpriced until the owner sets its fee; a percent-paid coach on such a class still gets the existing "requires a session price" 400.
- The Self-service change also blocks owners there; they change the terms in Billing rules, which already showed the same values.
- Rollback: revert this PR. No data to undo; the new audit actions stay readable as plain rows.
