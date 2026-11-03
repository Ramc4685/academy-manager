# mobile-push-in-app

PR: #TBD

## What changed
Inside the iOS and Android app, a signed-in admin, coach, parent or student is asked once for permission to receive notifications. If they allow it, the phone is registered for push and its token is saved to their account (`POST /api/v2/me/devices`). Signing out removes that phone from the account first (best-effort, at most three seconds), so the next person to use a shared family phone does not get the previous user's notifications. Tapping a notification opens the screen it points to; only links inside the app are followed. Nothing changes in a web browser: the push code only runs inside the app and is loaded on demand.

## Deploy notes
Needs the device-registration backend (`/api/v2/me/devices`, migration 0215) deployed first; until then the token upload fails quietly. The app shell gains the push plugin, the Android notification permission, and the iOS push entitlement and background mode, so it needs a new app build. Push stays off on Android until `google-services.json` is bundled, and real tokens on either platform need the Firebase app files.

## Risk / rollback
Push is best-effort: a denied permission, missing Firebase setup or a failed request is ignored with no error shown, and sign-out never waits on it. Revert this PR to remove it; tokens already stored stay unused until the sending slice (M3) ships.
