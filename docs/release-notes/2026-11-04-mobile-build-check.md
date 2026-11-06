# mobile-build-check

PR: #1128

## What changed
A new non-blocking workflow, Mobile Build Check, says on every push to `main` (and on PRs that touch `mobile/`) whether a new TestFlight / Play build is needed: "Mobile build needed: iOS / Android" with the changed native files, or "No mobile build needed". The baseline is the newest `ios-build-<n>` / `android-build-<n>` tag; until one exists the summary says "no baseline yet".

## Deploy notes
No server deploy. The owner places the first tag: `ios-build-5` on the commit TestFlight build 5 was archived from, then one tag per upload after that (`docs/runbooks/mobile-store-builds.md`).

## Risk / rollback
Information only: not a required check and not in the Production approval path, so a wrong answer or a failing run blocks nothing. Revert this PR to remove it.
