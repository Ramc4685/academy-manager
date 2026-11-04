# mobile-push-in-app

PR: #1115

## What changed
Inside the iOS and Android app, a signed-in admin, coach, parent or student is asked once for permission to receive notifications. If they allow it, the phone gets a Firebase Cloud Messaging token on both iOS and Android (`@capacitor-firebase/messaging`), which is saved to their account (`POST /api/v2/me/devices`). Signing out removes that phone from the account and deletes its token on the phone first (best-effort, at most three seconds), so the next person to use a shared family phone does not get the previous user's notifications. Tapping a notification opens the screen it points to; only links inside the app are followed. Nothing changes in a web browser: the push code only runs inside the app and is loaded on demand.

## Deploy notes
Needs the device-registration backend (`/api/v2/me/devices`, migration 0215) deployed first; until then the token upload fails quietly. The app shell gains the Firebase messaging plugin, the Android notification permission, and the iOS push entitlement and background mode, so it needs a new app build. Real tokens need the Firebase app files (`google-services.json`, `GoogleService-Info.plist`) and an APNs key uploaded to Firebase; without the files the app still launches and push stays quietly off.

## Risk / rollback
Push is best-effort: a denied permission, missing Firebase setup or a failed request is ignored with no error shown, and sign-out never waits on it. Revert this PR to remove it; tokens already stored stay unused until the sending slice (M3) ships.
