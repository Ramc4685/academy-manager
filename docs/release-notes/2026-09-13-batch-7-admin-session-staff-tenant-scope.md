# Batch 7: Admin session staff tenant scope

## What changed

- Fixes #543 — `attach_session_staff_names` (`backend/v2/composition/admin_session_staff.py`) read the global `users` collection by id with no tenant hop, so a coach/assistant id that was reused by or collided with another academy could render that other academy's person on an admin's session roster. Names are now attached only when the account holds an `academy_memberships` row in `current_academy_id()`, read fresh at execution time rather than captured at composition time. The membership hop is alias-aware (the roster's `user_id` vs. a membership's provisioned `firebase_uid`) and stays batched — one `users` `$in` plus one `academy_memberships` `$in`, no N+1. Ids with no membership in the current academy fall back to the existing unresolvable path (`coach_name` is `None`, the assistant is skipped) rather than leaking cross-tenant data. Shape mirrors `MongoAuditActorDirectory`, the documented precedent for this global-users + per-academy-membership join pattern.
- The N+1 half of the original issue (`payment_allocations` lookups) was already fixed on `main`; this PR only addresses the remaining unscoped-read half.

## Deploy notes

None. No migrations, no new indexes, no env vars, no feature flags. Pure backend read-path fix behind existing composition wiring.

## Risk / rollback

Low risk: the change narrows an existing read to be tenant-scoped and only removes staff names for ids that don't hold an academy membership in the current academy (previously those ids could render a person from a different academy). Covered by `backend/v2/tests/composition/test_admin_session_staff_names.py`. Rollback is a straight revert of this PR — no data changes to unwind.

PR: #0
