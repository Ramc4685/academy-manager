# Mobile store builds: when one is needed, and tagging uploads

The iOS and Android apps are a Capacitor shell that loads the live site
(`server.url` in `mobile/capacitor.config.ts`). A web deploy reaches installed
apps without a store build. Only a change to the native shell needs a new
TestFlight / Play upload: anything under `mobile/` (config, `ios/`, `android/`,
plugins in `package.json`, `assets/`, `www/`). Markdown files there do not count.

## The CI signal

`.github/workflows/mobile-build-check.yml` runs on every push to `main` and on
PRs that touch `mobile/`. Its job summary (and a notice on the run page) says
"Mobile build needed: iOS / Android" with the changed files, or "No mobile build
needed". It is information only: not a required check, not in the Production
approval path. Run it locally with `scripts/ci/mobile_build_check.sh`.

The baseline per platform is the newest tag named `ios-build-<n>` or
`android-build-<n>`, where `<n>` is the store build number. Without a tag the
check says "no baseline yet" instead of guessing.

## After uploading a build

Tag the exact commit the build was archived from, then push the tag:

```bash
git tag -a ios-build-6 <commit> -m "TestFlight build 6"
git push origin ios-build-6
```

Android works the same way with `android-build-<versionCode>`. Tag only after
the upload succeeds, and only the commit that was actually built (check
`git status` was clean when you archived).

## First tag (owner)

TestFlight build 5 is the latest iOS upload, but its source commit is not
recorded anywhere. Find it (the Xcode Organizer archive date, matched against
`git log -- mobile/`), then place `ios-build-5` on that commit. If it cannot be
pinned down, tag the next upload instead and start the baseline there. No
Android build has a tag yet either.
