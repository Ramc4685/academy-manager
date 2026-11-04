# mobile-dep-advisories

PR: #1122

## What changed
Bumps the Capacitor shell (`mobile/`) from 8.5.0 to 8.5.1 across core, CLI, Android and iOS, including the SwiftPM pin and resolved package, to clear critical advisory GHSA-rvm3-566m-v7fv. Adds version floors in `mobile/pnpm-workspace.yaml` for the transitive packages Dependabot cannot bump through a pnpm lockfile (tar, sharp, minimatch, grpc-js, uuid). `pnpm audit` for the shell is clean afterwards.

## Deploy notes
No web deploy, no migration. The next TestFlight and Play builds pick up Capacitor 8.5.1 on their normal `pnpm sync:release` path; nothing else changes.

## Risk / rollback
The only runtime change is the Capacitor patch release in the native shells; the web app is untouched. If a native build misbehaves, revert this PR and rebuild from the previous pins.
