# Support email, legal links and the Bank (ACH) discount switch

PR: #1012

## What changed

- Academy profile: new "Support email for parents" (`academies.support_email`, optional, validated). It is the default reply-to for academy email when no explicit reply-to is set (an explicit reply-to still wins) and the contact email in the public page footer (falls back to the contact email, as today, when unset). The Brand card's reply-to helper text now says it defaults to the support email.
- Academy profile: new "Legal links" card. Terms of service and Refund policy are new academy fields (`terms_url`, `refund_policy_url`, https only). Privacy notice is the existing `academies.public_page.privacy_notice_url` (same single stored value, so the trial form and CRM consent stamping are unchanged); it is edited here through `PATCH /admin/academy` and no longer on the Public page panel, which now shows a short pointer.
- Public page footer: shows the academy's terms and refund links when set. No refund link when unset; "Terms" keeps pointing at the platform page when unset.
- Billing rules: new owner-only, audited "Bank (ACH) discount" row (on/off and percent) in the Late payments box, written through `PUT /admin/billing/rules` with a `billing_rules_changed` audit entry (before and after). Percent must be above 0 and at most `billing_settings.max_ach_discount_percent` (default 3). The ceiling can never be written by a tenant: the billing settings upsert no longer persists it. Autopay only; Checkout does not apply it. The percent is still taken after the tuition discount (no math change).
- `GET /admin/academy` gains `support_email`, `terms_url`, `refund_policy_url`, `privacy_notice_url` (null when unset). `GET /public/academy` `page` gains `terms_url`, `refund_policy_url`.

## Deploy notes

- No migration. Every new field is read-time defaulted to unset; BLNO has no support email or legal links, so its emails, footer and billing behaviour do not change. BLNO's ACH discount stays whatever is stored (off / 0 if unset).
- Backend and frontend can ship in either order (new response fields are optional to the old frontend; the old frontend's Public page save still sends `privacy_notice_url`, which the endpoint still accepts).

## Risk / rollback

- Low. New fields are additive and optional. The one behaviour change with a live path is the reply-to fallback: it only applies to an academy that sets a support email and has no reply-to.
- Turning the ACH discount on changes what autopay bank payments are charged from the next attempt, and is owner-only and audited. Rollback: turn it off in Billing rules (or revert the PR); nothing is stored that the old code cannot read.
