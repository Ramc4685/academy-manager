# Android Google Play sign-in configuration

PR: TBD

## What changed
The Android app bundles the Firebase OAuth clients for Google Play signing and the current upload certificate. Builds installed from Google Play can use native Google sign-in with the registered certificates.

## Deploy notes
No server deploy or migration. Build a new Android bundle to pick up the refreshed config.

## Risk / rollback
Verify native Google sign-in on a Play-installed build before production rollout. Revert the config change and rebuild if the listing build needs to be rolled back.
