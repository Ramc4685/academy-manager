# push-device-registration

PR: #TBD

## What changed
Backend groundwork for push notifications in the mobile apps (slice M2): a signed-in user of any persona can register an app install's Firebase Cloud Messaging token with `POST /api/v2/me/devices` and remove it on logout with `DELETE /api/v2/me/devices/{token}`. Nothing is sent yet, and web behaviour is unchanged.

## Deploy notes
Migration `0215_push_devices` creates the new `push_devices` collection's indexes (unique `token`, plus `(academy_id, user_id)`). It runs on an empty collection, so it is instant and needs no manual step. No env vars.

## Risk / rollback
Low: two new endpoints that no shipped client calls yet. A token is unique across academies, so registering it moves it to the newest user (shared family phone). Roll back by reverting the PR; the empty `push_devices` collection and its indexes can stay.
