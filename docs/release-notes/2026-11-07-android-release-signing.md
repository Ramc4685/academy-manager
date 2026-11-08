# android-release-signing

PR: #1160

## What changed
- Android release builds can now be signed with the Play upload key. `mobile/android/app/build.gradle` reads it from an untracked `keystore.properties` (template: `keystore.properties.example`) or `ANDROID_KEYSTORE_*` env vars; without one the bundle builds unsigned as before. Key files and the properties file are gitignored.
- `versionCode` and `versionName` are set per upload with `-PversionCode` / `-PversionName` instead of editing the file.
- Runbook `docs/runbooks/mobile-store-builds.md` gains the Android release recipe, and `docs/plans/2026-11-07-play-store-listing-copy.md` drafts the Play listing text.

## Deploy notes
No web or API change. Only affects the next Play upload, which needs the owner's upload key.

## Risk / rollback
Low. Debug builds are untouched, and release builds without a key behave as before. Roll back by reverting the PR.
