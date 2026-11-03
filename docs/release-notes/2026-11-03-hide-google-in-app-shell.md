# hide-google-in-app-shell

PR: #TBD

## What changed
The login and registration pages no longer show "Continue with Google" inside the iOS/Android app shell (detected by the `window.Capacitor` global the shell injects). In the app, web Google sign-in cannot finish: the redirect to accounts.google.com opens in Safari, returns there without its starting state, and Firebase reports "missing initial state". The registration intro text drops its Google wording in the app. Browsers, including mobile Safari and Chrome, are unchanged. Native Google/Apple sign-in for the app comes later from the mobile branch.

## Deploy notes
Frontend only, no migration. Takes effect in the TestFlight build 1.0 (1) as soon as the frontend deploys, because the app loads the live site.

## Risk / rollback
Low: only hides a button where it could not work. Revert this PR to roll back.
