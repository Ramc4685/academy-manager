# iOS and Android apps — plan

Status: planning, spike shell built (2026-11-02). Owner-gated items marked **[owner]**.

## Approach

One backend, one API, one website. The apps are a Capacitor shell (`mobile/`) that
loads the deployed Next.js app from `server.url`. Website deploys update the apps;
a store release is only needed when the native shell changes (plugins, permissions,
icon). Every in-app behaviour is gated on `Capacitor.isNativePlatform()` so the
browser path stays byte-for-byte the same. Spike findings: `mobile/SPIKE.md`.

## Slices

Each slice is one PR with its own release note, CI gates as usual.

| # | Slice | Depends on | Blocked on |
|---|---|---|---|
| M0 | Shell scaffold + config (start URL, back gesture, status bar, App-Bound Domains, Stripe navigation) | — | Device run needs Xcode + Android Studio **[owner]** |
| M1 | Native Google sign-in + Sign in with Apple (frontend branch on native, `@capacitor-firebase/authentication`) | M0 | Firebase iOS/Android apps registered, `GoogleService-Info.plist` + `google-services.json`, Apple provider enabled in Firebase **[owner]** |
| M2 | Push device registration (backend): device-token store, `POST/DELETE /api/v2/me/devices`, migration for indexes | — | — |
| M3 | Push sending: `PushSendPort` (FCM via `firebase_admin.messaging`), stub + gated adapters, fan-out through the `ParentNotifier` service from the WhatsApp design (§5) | M2 | APNs auth key uploaded to Firebase **[owner]** |
| M4 | Push in the app: permission prompt, token registration on login, unregister on logout, tap opens the right screen | M1, M2 | — |
| M5 | In-app account deletion (Apple 5.1.1(v), Google Play) | — | Retention policy **[owner]**: what is deleted vs anonymised; invoices, payments and ledger rows must be kept for accounting |
| M6 | Store compliance: privacy policy URL, privacy labels / data safety form, age rating (not Kids category), icon + splash from one 1024px source | M0 | Listing copy, screenshots, final submit **[owner]** |
| M7 | Build pipeline: signed builds to TestFlight and Play internal testing (Fastlane) | M0 | Developer accounts, signing certificates **[owner]** |

Progress (2026-11-02 night):
- M0: shell configured (opens `/login`, iOS swipe-back, dark launch background,
  App-Bound Domains, Stripe kept in-app). Not yet run on a device.
- M1: frontend code done and unit-tested on `spike/capacitor-shell`
  (`frontend/lib/auth/native-sign-in.ts`; Google goes native in the app, "Continue
  with Apple" appears only in the iOS app). Native plugin installed in `mobile/`.
  Device test waits for the Firebase files below.
- M2: built on `feat/push-device-registration` (local commit, not pushed).
- M4: built on `feat/mobile-push-app` (local commit, not pushed;
  `frontend/lib/auth/native-push.ts`). Permission prompt and registration after
  the persona shell resolves, unregister on sign-out, notification tap opens
  same-origin `data.url` only. Android registers only when the shell bundles
  `google-services.json` (the `PushReady` marker in `MainActivity`), because
  `register()` crashes the app without it. **iOS gap for M3:**
  `@capacitor/push-notifications` reports the raw APNs token on iOS, not an FCM
  token, so `firebase_admin.messaging` cannot send to it. Fix before M3: either
  switch the app to `@capacitor-firebase/messaging` (FCM tokens on both
  platforms) or add FirebaseMessaging to the iOS app target and swap the token in
  `AppDelegate`.
- Owner decision: no PRs for M1 or M2 until the shell has run on a device.

## Decisions

- **Single app for all academies.** Persona routes resolve the academy from the
  signed-in user; only `/` is host-aware. The shell opens `/login`.
- **FCM for both platforms.** Firebase is already the identity provider; FCM fronts APNs.
- **Push is a channel, not a new notification system.** It plugs into the same
  fan-out as WhatsApp; email remains the channel of record and a push failure never
  fails or retries the email.
- **Old shells stay in the wild.** Native features are capability-checked
  (`Capacitor.isPluginAvailable`), never version-checked.

## Owner checklist

- [ ] Free ~50 GB, install Xcode (App Store) and Android Studio.
- [ ] Decide the publishing legal entity; request a D-U-N-S number if needed.
- [ ] Enroll: Apple Developer Program (organization), Google Play Console (organization).
- [ ] Confirm app ID (`com.courtmastr.academy` placeholder) and store name.
- [ ] Firebase console: add an iOS app and an Android app with that ID; download
      `GoogleService-Info.plist` and `google-services.json`; enable the Apple provider.
      Hand both files to Claude; they go in `mobile/ios/App/App/` and
      `mobile/android/app/` (the iOS one also supplies the `REVERSED_CLIENT_ID`
      URL scheme Google sign-in needs).
- [ ] Android Google sign-in: register the debug and release signing SHA-1
      fingerprints on the Firebase Android app (Claude can print the debug one
      once Android Studio is installed).
- [ ] Apple Developer portal: enable the "Sign in with Apple" capability on the app ID.
- [ ] Apple Developer portal: enable Push Notifications on the app ID (the project
      already carries the `aps-environment` entitlement and the remote-notification
      background mode; a free personal team cannot sign it), create an APNs auth
      key and upload it to Firebase (Project settings > Cloud Messaging).
- [ ] In Xcode, open the App target's Signing & Capabilities once to confirm Push
      Notifications and Background Modes > Remote notifications show up.
- [ ] Decide account-deletion retention (M5).
- [ ] Is there a staging deployment to point test builds at? None found in the repo.

## Risks

- M2 token takeover (flagged by the automated security review and by the build
  agent): `register` moves a token row across users and academies on the caller's
  word alone, so anyone holding another phone's FCM token could redirect its
  pushes. Before the M2 PR, at minimum, log every cross-user or cross-academy move
  as an audit event. Decide in M3 between proof-of-possession (a challenge push
  the app echoes back) and per-academy rows, with the sender checking which
  registration is most recent.

- App-Bound Domains (needed for the iOS service worker) caps in-webview hosts at 10;
  any host Firebase, Sentry or fonts load inside the webview must be listed.
- Apple guideline 4.2 rejects thin web wrappers; push (M3/M4) and native sign-in
  (M1) are the native value.
- Google Play requires new personal accounts to run a 14-day closed test with 12+
  testers; organization accounts avoid it.
