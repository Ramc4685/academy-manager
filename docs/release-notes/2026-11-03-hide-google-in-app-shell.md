# hide-google-in-app-shell

PR: #1112

## What changed
In the iOS app, Google sign-in now runs through Google's own SDK, not the website's redirect, and Sign in with Apple appears next to it (App Store guideline 4.8). The native SDK hands its token to the web Firebase session (`frontend/lib/auth/native-sign-in.ts`), so sign-in never leaves the app for Safari. That Safari detour is what caused Firebase's "missing initial state" error.

The app shows Google and Apple only when its build says it can sign in natively: its user agent carries `CourtMastrNativeAuth/1`, set by builds that bundle their Firebase config. Older builds (TestFlight 1.0 (4) and earlier) and Android show email/password only, with no broken Google button. Browsers, including mobile Safari and Chrome, are unchanged.

## Deploy notes
Frontend only, no migration. Adds `@capacitor-firebase/authentication` and `@capacitor/core`; they load on demand inside the app only, never in a browser. Once deployed, build 4 hides Google right away. TestFlight 1.0 (5), built from `spike/capacitor-shell` with the Firebase iOS config, shows native Google and Apple.

Firebase is already set up (2026-11-03): iOS app registered, and the Apple provider enabled for `com.courtmastr.academy`.

## Risk / rollback
Limited to the app. An Apple user who picks "Hide My Email" gets "We couldn't find an account for your email", because the backend matches by email. Email/password is untouched. Revert this PR to roll back. Build 4 would then show the broken Google button again.
