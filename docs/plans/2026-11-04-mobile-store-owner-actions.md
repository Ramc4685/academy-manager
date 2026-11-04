# Mobile store release: what only the owner can do (2026-11-04)

Phase 3 of the publish checklist (`2026-11-03-publish-checklist.md`) is built on
`spike/capacitor-shell`: parent push events, `pnpm sync:release`, no `localhost`
in Release App-Bound Domains, and CSV/print hidden in the app. What is left needs
the owner's accounts, devices or decisions. Nothing below has been created for you.

## 1. Android release signing (`signingConfigs`)

The app has no release `signingConfigs` yet (`mobile/android/app/build.gradle`
only sets `minifyEnabled false`). Google Play uses **Play App Signing**: Google
keeps the key that signs what users install, and you sign uploads with your own
**upload key**. To wire that up we need, from you:

1. **An upload keystore you create and keep.** For example
   `keytool -genkeypair -v -keystore courtmastr-upload.jks -alias upload -keyalg RSA -keysize 2048 -validity 10000`
   (JDK 21, the same one Gradle uses). Keep the `.jks` file **out of the repo**
   (store it in your password manager or an encrypted backup). Losing it means a
   Play support request to reset the upload key, not a lost app, but it is slow.
2. **Four values**, given to the build through a local, untracked
   `mobile/android/keystore.properties` (or CI secrets), never in chat or git:
   `storeFile` (path to the `.jks`), `storePassword`, `keyAlias` (`upload` above),
   `keyPassword`. Once these exist, the Gradle `signingConfigs.release` block that
   reads them is a few lines; ask and it will be added.
3. **Play Console finished.** The "Marvy Labs LLC" organization account still needs
   your identity document and then phone verification. After that, create the app
   with package name `com.courtmastr.academy` (permanent once published) and keep
   Play App Signing on (the default).
4. **Firebase Android app + SHA fingerprints.** In the Firebase project, register
   (or confirm) the Android app `com.courtmastr.academy`, then add three SHA-1
   (and SHA-256) fingerprints: your upload key (`keytool -list -v -keystore ...`),
   and, after the first upload, the **App signing key certificate** shown in Play
   Console > Test and release > App integrity. Without the Play one, Google
   sign-in fails in every store-installed build.
5. **`google-services.json`.** Download it from Firebase after step 4 and place it
   at `mobile/android/app/google-services.json`. It turns on native Google sign-in
   and push on Android (the build detects the file).
6. **Store listing answers** you own: Data safety form (match the privacy policy),
   content rating questionnaire, target audience (the app is for parents and
   staff, so 18+ keeps it out of the Families program), and the privacy policy URL
   (still waiting on counsel review).
7. **`versionCode`** must go up for every upload (it is `1` now in
   `build.gradle`). Tell the build session the next number, or let it bump it.

## 2. Turning push on

The four parent events (class date cancelled, waitlist seat offered, urgent
announcement, dues reminders) are wired but send nothing until you:

1. **iOS:** create an APNs auth key (Apple Developer > Keys, Team `8MZNKJY4N3`,
   enable Apple Push Notifications service) and upload the `.p8` to Firebase >
   Project settings > Cloud Messaging > Apple app configuration.
2. **Android:** steps 4 and 5 above (`google-services.json`).
3. **Server:** set `PUSH_DELIVERY_ENABLED=true` on the API (Fly secret) after the
   branch is deployed. Setting it back to `false` stops all pushes without a deploy.
4. **Check on a phone:** on the next TestFlight build, cancel a test class date for
   a test family and confirm the push arrives and opens the parent home.
   `App.entitlements` says `aps-environment: development`; the App Store export
   should re-sign it as `production`. Confirm with
   `codesign -d --entitlements - Payload/App.app` on the exported IPA.

## 3. Release build recipe change

Use `cd mobile && pnpm sync:release` before archiving (it sets `MOBILE_RELEASE=1`
and the BLNO server), then `pnpm sync` afterwards to return to local dev. The
Release build drops `localhost` from App-Bound Domains on its own.

## 4. Still open from earlier phases

- Device test pass of the latest TestFlight build (sign-in, Stripe Checkout,
  offline attendance, push).
- Counsel review of the privacy policy, then remove its draft banner.
- Push and merge `spike/capacitor-shell`, then deploy backend and frontend.
