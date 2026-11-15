# dependabot-majors-split

PR: #TBD

## What changed
- Dependabot: grouped version-update PRs (backend, frontend, docker, GitHub Actions) now carry minor and patch updates only. Each major upgrade arrives as its own PR, so one breaking package can no longer stall the safe bumps grouped with it. #1161 sat red for a week because `@sentry/browser` 11 and `@fullcalendar/core` 7 broke the frontend type check.
- GitHub Actions: `actions/download-artifact` 7 → 8 (index drift audit), `actions/setup-java` 6.0.0 → 6.1.0, and `getsentry/action-release` moved to a newer v3 commit. Replaces #1094.

## Deploy notes
None. CI and Dependabot config only; no app code, migration or env var.

## Risk / rollback
Low. The drift audit uploads a normal zipped artifact, which `download-artifact` v8 extracts the same way v7 did. Roll back by reverting the PR.
