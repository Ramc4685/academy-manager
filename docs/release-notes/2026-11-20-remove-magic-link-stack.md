# remove-magic-link-stack

PR: TBD

## What changed
The parent magic-link sign-in is gone: the `POST /api/v2/magic-link/consume` route, its use case and repository, and the `/auth/magic` page are deleted. The last links were minted before #1202 deployed on 2026-11-17 and their 72h window has closed. The backend also stops accepting Firebase sessions with the `custom` sign-in provider, which only magic links ever produced: a parent still holding one of those sessions gets the normal "please sign in again" 401, whether or not their email is verified, because the session may belong to whoever a link was forwarded to.

## Deploy notes
- No migration and no settings change. The `parent_magic_links` collection is left in place: its TTL index (0149) empties it by about 2026-11-27, and account deletion still erases its rows early. A later migration can drop the empty collection.
- Owner step after deploy (needs explicit owner approval: it writes to production Firebase). The API refuses leftover sessions, but each one's Firebase refresh token still mints ID tokens, so its holder can call Firebase client APIs directly, for example to link a Google or password credential onto the parent's uid and keep access through a non-custom provider. List the affected users read-only with `mongosh "$MONGO_URL" --quiet scripts/ops/list_magic_link_sessions.js` (every `user_logged_in` audit row with `metadata.provider == "custom"`). Run a one-off Firebase Admin `revoke_refresh_tokens(uid)` for each listed uid, then check each user's `provider_data` for providers the parent didn't add. Revoking signs those users out on every device.

## Risk / rollback
- Risk: a parent who signed in through a magic link and never set a password is signed out and has to use "Forgot password?" on the sign-in page. That is the intended trade.
- Rollback: revert the PR. Nothing is stored differently.
