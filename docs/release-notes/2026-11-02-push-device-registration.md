# push-device-registration

PR: #TBD

## What changed
Backend groundwork for push notifications in the mobile apps (slices M2 and M3).

- A signed-in user of any persona can register an app install's Firebase Cloud Messaging token with `POST /api/v2/me/devices` and remove it on logout with `DELETE /api/v2/me/devices/{token}`.
- A token moves to whoever registers it last (a shared family phone). Every move to a different user or academy now writes a `push_device.token_moved` row to `audit_logs` in the academy the token moved into, with the previous and new `user_id`/`academy_id`. The row holds a 16-character SHA-256 fingerprint of the token, never the token itself.
- Push sending: a new `send_push_to_user` use case sends a title, body and data to every device a user holds in an academy, and deletes tokens FCM reports as unregistered or invalid. Email stays the channel of record: a push failure is logged and never raised to the caller. Nothing calls it yet; the planned `ParentNotifier` (WhatsApp design §5) is the hook-up point.

Web behaviour is unchanged.

## Deploy notes
Migration `0215_push_devices` creates the new `push_devices` collection's indexes (unique `token`, plus `(academy_id, user_id)`). It runs on an empty collection, so it is instant and needs no manual step.

New env var `PUSH_DELIVERY_ENABLED` (or `V2_PUSH_DELIVERY_ENABLED`), default off. While off, pushes go to an in-memory stub and nothing reaches a phone. Turning it on uses the existing Firebase Admin credentials; no new secret.

## Risk / rollback
Low: two new endpoints that no shipped client calls yet, and a sender that is off by default and has no caller. Roll back by reverting the PR; the `push_devices` collection, its indexes and any `push_device.token_moved` audit rows can stay.
