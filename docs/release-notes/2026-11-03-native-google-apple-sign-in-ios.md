# native-google-apple-sign-in-ios

PR: #1115

## What changed
The iOS app can now sign in with Google and Apple natively. The app bundles its Firebase config (`GoogleService-Info.plist`, from the new Firebase iOS app `1:953230788846:ios:e11694e0f21ba8d0860bff`), registers Google's reversed client ID as a URL scheme, and carries the Sign in with Apple entitlement. Google's own SDK signs the user in through the system sign-in sheet and hands its token to the web Firebase session, so sign-in no longer goes through Safari. That Safari detour is what caused the "missing initial state" error in TestFlight 1.0 (4).

The web app shows Google and Apple only when the app build says it can sign in natively. `mobile/capacitor.config.ts` adds `CourtMastrNativeAuth/1` to the user agent only for a platform whose Firebase config file is present, and `canUseNativeSignIn()` checks for it. Before this, the check only looked for the plugin, which build 4 has even though it cannot sign in. Builds without the marker (build 4, and Android until `google-services.json` lands) keep Google and Apple hidden and show email/password only. Browsers are unchanged.

## Deploy notes
Done in Firebase (prod project `academy-courtmastr`) on 2026-11-03: the iOS app was registered for `com.courtmastr.academy`, and the Apple sign-in provider was enabled for that bundle ID. Native iOS needs no Services ID or key.

To take effect: deploy this branch's frontend, then ship a new iOS build (`cap sync ios` from `mobile/` so the user agent marker is applied). Build 4 is unaffected either way.

The bundled Firebase config also switches on iOS push token registration. Tokens fail quietly until an APNs key is uploaded to Firebase.

Android is not covered: it needs `google-services.json` plus debug, upload and Play App Signing SHA-1s registered in Firebase.

## Risk / rollback
An Apple user who picks "Hide My Email" signs in to Firebase with a private relay address. The backend matches users by email only, so that user gets "We couldn't find an account for your email" and no access. This fails closed but needs account linking before it is smooth. An Apple user whose real email already has a password account gets the existing "account already exists with a different sign-in method" message.

To roll back, revert this commit and ship a new build. Removing `GoogleService-Info.plist` alone also drops the marker, which hides Google and Apple again.
