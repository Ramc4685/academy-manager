# audience-academy-scoping

PR: #577

## What changed
`resolve_academy_audience` and `resolve_payment_risk_audience` fetched user
docs with a `user_id`/`auth_uid` `$or` but no `academy_id` filter. Because the
users collection holds one doc per (user, academy) for multi-academy users
(shipped with the multi-persona/additive-role feature), a parent or coach in
two academies matched two docs — and `SendCampaign` iterates recipients with
no dedup, so that meant two real emails and two Delivery rows, possibly one of
them at a stale email pulled from the other academy's user doc. Both resolver
paths now go through a shared `_resolve_users_for_ids` helper that scopes the
users query to `{"academy_id": {"$in": [current_academy_id(), None]}}` —
matching the current tenant's doc or a legacy global doc that has no
`academy_id`, never another academy's — and dedupes results by `user_id`,
preferring the tenant-scoped doc so its email and display name win over a
global fallback. The payment-risk path's previous three-branch `$or`, which
mixed unscoped and academy-scoped matches, collapses into the same helper.

Two follow-ups from review landed on the same branch:

- The payment-risk resolver no longer narrows delinquent ids to active
  `academy_memberships` docs before resolving. Every id from this academy's
  overdue invoices/payments is resolved directly, so a delinquent parent with
  a tenant-scoped (or legacy global) user doc but no active membership doc is
  still reached — the previous membership filter would have silently dropped
  them whenever at least one other delinquent parent did hold a membership.
- `SendCampaign` now dedupes resolved recipients before any email leaves
  (belt-and-suspenders, first occurrence wins): by `user_id` and, when
  present, by normalized email. This closes the residual duplicate path where
  one person resolves through two user docs (one matched by `user_id`, one by
  `auth_uid` carrying a different `user_id`).

## Deploy notes
No migration and no new indexes — the scoped query uses the same fields the
existing unscoped one did. No API or frontend changes. Digest paths were
already protected from duplicates by the claim index; this fix removes the
`already_claimed` noise those duplicates generated there.

## Risk / rollback
The tenancy change is strictly narrowing: recipients that previously
resolved from another academy's user doc (duplicates or stale-email matches)
no longer resolve. One deliberate widening: a membership-less delinquent
parent whose only user doc is a legacy global one (no `academy_id`) is now
reached by payment-risk campaigns, where before they matched only via a
tenant-scoped doc. A user whose only doc belongs to a different academy while
their membership sits in this one would now be dropped — that state would
itself be data corruption, and the legacy-global allowance (`academy_id`
absent) keeps every pre-multi-tenant user doc resolving exactly as before.
Roll back by reverting the merge commit; no persisted state changes.
