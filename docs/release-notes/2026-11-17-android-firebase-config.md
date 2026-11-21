# android-firebase-config

PR: #1208

## What changed
The Android app now ships with its Firebase configuration (`mobile/android/app/google-services.json`). New Android builds register for push notifications and show native Google sign-in, as the iOS app already does. Nothing changes for web users or for Android phones still running an older build.

## Deploy notes
- No backend or frontend deploy is needed; this takes effect in the next Android app build.
- Push still reaches no phone until `PUSH_DELIVERY_ENABLED=true` is set on the production backend.
- Google sign-in works for builds signed with the registered debug or local release key. Builds re-signed by Google Play App Signing need that key's fingerprint added in Firebase and this file refreshed.

## Risk / rollback
- Risk: low. The file holds app identifiers and Firebase API keys restricted to this package and its signing certificates; it is not a server secret.
- Rollback: revert the PR. Android builds then skip the Google services plugin, hide native Google sign-in and stop registering for push.
