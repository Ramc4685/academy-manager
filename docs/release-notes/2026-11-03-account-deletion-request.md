# account-deletion-request

PR: #1115

## What changed
Backend for self-service account deletion, which Apple and Google require before the mobile apps can ship (slice M5, part D1). Nothing in the web or app UI calls it yet; the Delete account screen is part D2.

- `POST /api/v2/me/account-deletion` with `{"confirm": "DELETE"}` lets a signed-in user of any persona delete their own account. It needs a sign-in from the last 5 minutes (the ID token's `auth_time`), so the screen will ask for the password or Google/Apple sign-in again first. Otherwise it answers 403 `Identity.RecentSignInRequired`.
- The request refuses two cases that would strand an academy. The only owner of an academy gets 409 `Identity.CannotRemoveLastOwner`. A coach or assistant coach who still has upcoming classes gets 409 `Identity.CoachHasFutureSessions` until an admin reassigns them. An unpaid balance does not block deletion.
- An accepted request locks the account in every academy at once: memberships become `removed`, the Firebase account is disabled (best-effort, as with the admin disable), and push tokens are deleted. It also writes one `user.deletion_requested` audit row per academy and a row in the new `account_deletion_requests` collection with `execute_after` 14 days out. Asking again returns the request already on file.
- Nothing is anonymised or deleted yet. The scheduled clean-up of personal data is part D3; until it ships, a request only locks the account.
- Signed-in claims now carry `signed_in_at` (the token's `auth_time`).

## Deploy notes
Migration `0216_account_deletion_requests` creates the new collection's indexes (unique `user_id`, plus `(status, execute_after)` for the D3 job). It runs on an empty collection, so it is instant and needs no manual step. No new env vars or secrets.

## Risk / rollback
Low: one new endpoint that no shipped client calls yet. An accepted request is reversible until its erasure starts: platform support cancels it with `POST /api/v2/platform/account-deletions/{request_id}/cancel`, which restores every academy's membership and re-enables the Firebase login; the academy Enable action refuses a person with a pending request. Roll back the code by reverting the PR; the collection and its indexes can stay.
