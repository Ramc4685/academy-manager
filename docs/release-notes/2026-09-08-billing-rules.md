# billing-rules

PR: #688

## What changed
Settings gains one owner-only **Billing rules** panel replacing the Fees and Invoice-schedule panels. It shows every number that decides when money moves, each row marked editable or fixed: invoice day and days until due, grace days and late fee, the cancellation notice and fee, plus fixed statements of the 09:00 charge time, the retry ladder, the cancel/join/paused policies and which emails parents get. Fixed values are derived from the constants that govern the behaviour, so the page cannot drift from the worker. A new `GET`/`PUT /admin/billing/rules` pair validates everything before writing and records one `billing_rules_changed` audit entry — fee changes were previously unaudited. The dead `default_monthly_cents` field is removed.

## Deploy notes
No migration. `default_monthly_cents` disappears from the fees API and both seed scripts; existing `academies` documents keep the key harmlessly (no validator forbids it). The legacy `PATCH /admin/academy/fees`, `GET/PUT /admin/billing/settings/invoice-schedule` and the self-service policy routes are unchanged for their other callers. `?panel=fees` now lands on Billing rules.

## Risk / rollback
**The late fee and grace days are stored but still not applied by anything** — no code charges a late fee, and the panel says so on its face. Do not read the presence of these fields as the feature existing. `FIRST_ATTEMPT_LOCAL_HOUR` moved from the dunning repository into the dunning domain; it is a pure move and the 09:00 first-attempt gate is unchanged, but it is the constant that decides when parents are charged, so it is worth a glance in review. Rollback by reverting; nothing stored changes shape.
