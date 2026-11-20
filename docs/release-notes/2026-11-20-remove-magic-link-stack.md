# remove-magic-link-stack

PR: TBD

## What changed
The parent magic-link sign-in is gone: the `POST /api/v2/magic-link/consume` route, its use case and repository, and the `/auth/magic` page are deleted. The last links were minted before #1202 deployed on 2026-11-17 and their 72h window has closed. The backend also stops accepting Firebase sessions with the `custom` sign-in provider, which only magic links ever produced: a parent still holding one of those sessions gets the normal "please sign in again" 401, whether or not their email is verified, because the session may belong to whoever a link was forwarded to.

## Deploy notes
- No migration and no settings change. The `parent_magic_links` collection is left in place: its TTL index (0149) empties it by about 2026-11-27, and account deletion still erases its rows early. A later migration can drop the empty collection.
- No production revoke is needed: leftover sessions are refused on their next request. If the owner wants them gone at the Firebase level too, revoke refresh tokens for users with a `metadata.provider == "custom"` login row in `audit_logs`.

## Risk / rollback
- Risk: a parent who signed in through a magic link and never set a password is signed out and has to use "Forgot password?" on the sign-in page. That is the intended trade.
- Rollback: revert the PR. Nothing is stored differently.
