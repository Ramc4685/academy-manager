# Restoring a self-deleted account (support only)

A person who deletes their own account (in the app, or via `/account-deletion`) is locked out of every academy at once, and their personal details are erased 14 days later. Restore is **support-only** (owner decision on PR #1115): an academy admin cannot undo it, and the admin Enable action refuses with `Identity.AccountDeletionPending` while the request is pending.

## When you may restore

- The person asked for it, and you confirmed it is really them (reply from the account's email address, or a call to the phone number on file). An academy asking on their behalf is not enough.
- The erasure has not started. Once the hourly job has claimed the request, or any attempt has run (even one that failed partway), it cannot be restored and is retried until it finishes. The route answers 409 `Identity.AccountDeletionInProgress` in that case.

## Find the request

Admins of each academy see the request on the family page and in `GET /api/v2/admin/account-deletions` (`request_id` is in each row). Without an admin, look it up read-only on production:

```js
db.account_deletion_requests.find(
  { email: "person@example.com" },
  { request_id: 1, status: 1, attempts: 1, claimed_at: 1, academy_ids: 1, execute_after: 1 }
)
```

Restorable means `status: "scheduled"`, no `claimed_at`, and no `attempts` (or 0).

## Cancel it

As a platform admin or platform support user:

```
POST /api/v2/platform/account-deletions/{request_id}/cancel
{ "reason": "confirmed by phone with the parent on 2026-11-05" }
```

This cancels the whole request: every academy's memberships return to the status they had before the deletion (a suspended member stays suspended), the Firebase login is re-enabled, the request row is removed, and a `account_deletion.cancelled_by_support` platform audit row is written for each academy, carrying the reason.

If the response says `"firebase_enabled": false`, the memberships are back but Firebase could not be reached: re-enable the user in the Firebase console (Authentication, the account's uid), because calling the route again finds no request.

Anyone without a platform role gets 404, as on the other platform routes.
