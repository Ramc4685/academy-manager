# Pricing page under Money (Settings overhaul Phase 3 PR 11b)

PR: #TBD

## What changed

- **New owner-only page `/admin/pricing`** with a "Pricing" item under MONEY right after Payments. Plain admins do not see the item; opening the URL shows the owner-only panel. Every new API route answers a plain admin with 403 "Only the academy owner can see and change pricing." (anyone without an admin role still gets 404).
- **Plans:** the Settings "Session types" tab moved here as "Plans" (same data, same owner-only `/admin/session-types` writes). Settings no longer has the tab; `/admin/settings?panel=session-types` redirects to `/admin/pricing`. The dashboard setup step is now "Pricing plans" and links to `/admin/pricing`.
- **Plan type:** every plan reads as "Monthly · 4 classes, 5th free" (today's rule), filled at read time. "Per session" is shown as coming later and cannot be saved; the API accepts only `plan_type: "monthly"`. No billing code reads the plan type.
- **Where each class's price comes from:** each class with the plan it uses (or Custom), what it is charged per month and its active students. "Charged / month" is the class's own monthly fee, read with the monthly invoice generator's own helper. The owner can link a class only to an active plan at exactly its fee, or mark it Custom (`PUT /api/v2/admin/pricing/classes/{session_id}/plan`, 409 on a price mismatch). "Link matching classes" (`POST /api/v2/admin/pricing/link-matching-classes`) links each undecided class to the one plan at its fee; zero or several matches stay Custom, and a class the owner already decided is never touched. A link whose plan price later moves away from the fee shows as Custom.
- **Links are labels, never amounts.** They live in a new billing-owned collection `class_plan_links` that no charge path reads. Checkout quotes, monthly invoices, "Bill this month" and cancellation credits keep reading the class fee exactly as before (tests prove a linked class is billed its own fee after its plan price changes). Link changes are audited in `billing_audit_log` (`class_plan_link_changed`, `class_plan_links_matched`).
- **Saved price overrides:** a read-only list of amounts saved by the two owner "override price" buttons (Student > Billing plans > Override price, Student > Sessions > Override fee), beside what is actually charged. Nothing converts them into prices. Empty state when there are none.
- **Display fixes (no charge path touched):**
  - Parent class list: a class with no fee showed a $150 placeholder; it now shows $0.00, which is what the checkout quote and monthly invoice charge an unpriced class.
  - Family page, Students panel: the monthly price shown is the class fee as billed (new `class_fee_cents`, which reads `amount_cents` first like the generator) instead of the saved override; an override is labelled "saved override, not charged".

## Deploy notes

- No migration. `plan_type` is filled at read time; `class_plan_links` is created on the first link. No existing document is changed.
- BLNO's bills do not change: no amount is written anywhere and no charge path reads the new collection or field. BLNO starts with every class Custom until the owner clicks "Link matching classes" or picks plans.

## Risk / rollback

- Risk: an owner reads "Custom" or a stale link as a pricing problem; the page says every bill uses the class fee. `class_plan_links` has no unique index yet (no migration in this PR), so two simultaneous first links of the same class could leave two rows; reads take either and both carry a plan at the class fee.
- The family page's manual-invoice pre-fill still reads the legacy `monthly_price_cents` (listed as a follow-up; changing it would touch a charge path).
- Rollback: revert this PR. The `class_plan_links` rows and audit entries can stay; nothing reads them after a revert.
