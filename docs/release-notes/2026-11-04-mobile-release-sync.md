# mobile-release-sync

PR: #TBD

## What changed
`pnpm sync:release` in `mobile/` runs `cap sync` with the store-build settings: `MOBILE_RELEASE=1` and the BLNO server (`https://blno-academy.courtmastr.com`, overridable with `MOBILE_SERVER_URL`), so a release sync can no longer point at localhost over cleartext. iOS Release builds now drop the dev-only `localhost` entry from `WKAppBoundDomains` in the built app through a new Xcode build phase (`mobile/scripts/strip-dev-bound-domains.sh`); the source `Info.plist` keeps it so simulator runs against `next dev` still work. `pnpm test` in `mobile/` checks the strip script, the build phase and the release script.

## Deploy notes
No server deploy. Use `pnpm sync:release` before archiving instead of setting the environment by hand; run `pnpm sync` afterwards to go back to the local dev server. Takes effect from the next app build.

## Risk / rollback
Only the built Release app changes, and only that one bound-domain entry; Debug builds are untouched. A Release simulator build was checked: its `WKAppBoundDomains` is academy, blno-academy and checkout.stripe.com. Revert this PR to remove the script and build phase.
