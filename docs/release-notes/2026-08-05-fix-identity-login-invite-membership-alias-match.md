# Login-invite membership matching by identity alias

PR: #400

## What changed
- `get_login_invite_user` and `record_login_invite` required the `users` doc to carry a `firebase_uid` and matched the `academy_memberships` row on that field only. Parents whose membership row is keyed by the plain `user_id` instead (legacy/imported records with no `firebase_uid`) were invisible to the invite flow, so "Send login invite" returned 404 for them even though the same account loaded fine in the admin directory and could otherwise log in.
- This disagreed with the actual login path: `load_auth_claims` resolves membership via `user_id`, not `firebase_uid` — so an account could be able to sign in while being un-invitable.
- Both methods now match the active membership against any known identity alias (`user_id`, `auth_uid`, `firebase_uid`), the same pattern `_id_filter` already uses for the initial user lookup.
- Adds `backend/scripts/parent_account_audit.py`, a read-only report of which parents can log in, which have a working invite button, and which still need credentials sent.

## Deploy notes
No migration, environment variable, or manual deployment step is required. Affected parents become invitable as soon as the backend is deployed; no data backfill is needed.

## Risk / rollback
Matching on any alias slightly widens membership resolution for the invite path: a `users` doc whose aliases collide with another account's membership row could resolve to that membership. Aliases are unique per account in practice, and the lookup stays scoped to `academy_id` + `status: "active"`, so cross-tenant resolution remains impossible. Revert PR #400 to restore `firebase_uid`-only matching; parents with `user_id`-keyed membership rows will again 404 on "Send login invite".
