# Login membership matching by identity alias

PR: #TBD

## What changed
- `LoadAuthClaims` resolved the caller's `academy_memberships` row by an exact `user_id` match. `ensure_parent_login` / `ensure_student_login` preserve a pre-existing roster `user_id` on the `users` doc while keying the new membership row by the freshly provisioned `firebase_uid`, so the two legitimately diverge. Those parents signed in to Firebase successfully and were then rejected with a bare 401 from `/api/v2/me` and silently bounced back to the login page.
- The login path now matches the membership row against every identity alias of the already-resolved user (`user_id` plus `firebase_uid`/`auth_uid`), the same alias semantics PR #400 gave the login-invite path. The two checks now agree: an account that can be invited can also log in.
- `MembershipLookup.get_for_user_in_academy` and `MongoMembershipRepository.get_membership` take an optional `aliases` argument and widen only the identity term of the query (`user_id: {$in: [...]}`). `academy_id` remains a mandatory, explicit term, so tenant isolation is unchanged.
- Aliases are read off the resolved `users` document, never off the Firebase token, so a token cannot inject an alias to claim someone else's membership.
- Regression tests: a membership keyed by the account's `firebase_uid` now resolves login claims (`v2/tests/application/test_load_auth_claims.py`), the same alias lookup still refuses another academy's membership, and the Mongo repo contract covers both cases.

## Deploy notes
No migration, environment variable, or manual step. Affected parents can log in as soon as the backend is deployed; no data backfill is required. `backend/scripts/parent_account_audit.py` (added in PR #400) reports the affected population before/after.

## Risk / rollback
Alias matching widens which identifiers resolve a membership row within a single academy: a `users` doc whose aliases collided with another account's membership row could resolve to that membership. Aliases are unique per account in practice (unique sparse indexes on `firebase_uid`), and the query stays scoped to the explicitly resolved `academy_id`, so cross-tenant resolution remains structurally impossible and the existing `is_active()` check is untouched. Rollback: revert this PR to restore exact `user_id` matching; the affected parents will again receive a 401 at `/api/v2/me`.
