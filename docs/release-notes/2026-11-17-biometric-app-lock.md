# biometric-app-lock

PR: TBD

## What changed
Coaches and parents using the iOS/Android app can turn on "Lock with Face ID" (or fingerprint) from their profile. The app then asks for a face, fingerprint or phone passcode when it opens and after a minute in the background, and covers the screen in the app switcher. It is off by default, set per phone, and switched off by sign-out.

## Deploy notes
Web deploy: none. The toggle only shows in app builds that ship the new `@capgo/capacitor-native-biometric` plugin, so a new TestFlight and Play build is needed before anyone sees it (`docs/runbooks/mobile-store-builds.md`).

## Risk / rollback
Worst case is a person stuck at the lock screen: the passcode fallback and "Sign out instead" both get them out, and sign-out clears the setting. Roll back by reverting; older app builds never show the toggle.
