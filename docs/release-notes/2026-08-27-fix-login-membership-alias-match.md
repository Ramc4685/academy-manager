# Login membership matching by identity alias

PR: #438

## What changed
`LoadAuthClaims` resolved the caller's `academy_memberships` row by an exact `user_id` match, but `ensure_parent_login` / `ensure_student_login` keep a pre-existing roster `user_id` on the `users` doc while keying the new membership row by the provisioned `firebase_uid` — so affected parents signed in to Firebase successfully and were then rejected with a bare 401 from `/api/v2/me`. The login path (and `/me/memberships`, which returned "you belong to no academies" for the same accounts) now matches every identity alias of the resolved user, the semantics PR #400 already gave the login-invite path. All three call sites now share one alias helper in `contexts/identity/domain/identity_aliases.py`, and when several rows match, the active row wins, then the exact `user_id` hit, then `membership_id` — a deterministic order rather than Mongo's natural one.

## Deploy notes
No migration, environment variable, or manual step. Affected parents can log in as soon as the backend is deployed; no data backfill is required. `backend/scripts/parent_account_audit.py` (added in PR #400) reports the affected population before/after.

## Risk / rollback
Alias matching widens which identifiers resolve a membership row within one academy, so an account whose alias equals another account's membership `user_id` would resolve to that row. Nothing constrains `academy_memberships.user_id` against other accounts' aliases — the unique index on `users.firebase_uid` does not cover this — so the mitigation is the ranking above (an exact `user_id` hit is preferred over an alias hit) plus the alias set being read off the caller's own resolved `users` document rather than the token. Tenant scope is untouched: `academy_id` remains an explicit, mandatory term in every query and the `is_active()` check is unchanged, so cross-tenant resolution stays structurally impossible. Rollback: revert this PR to restore exact `user_id` matching; the affected parents will again receive a 401 at `/api/v2/me`.
