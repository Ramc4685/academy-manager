# Unblock the production run: urllib3 2.8.0 and a class-first e2e race

PR: #TBD

## What changed
- Backend: `urllib3` bumped from 2.7.0 to 2.8.0 for CVE-2026-97687, CVE-2026-97688 and CVE-2026-97689. The dependency audit was failing the production run.
- E2E: `parent-onboarding-class-first.spec.ts` waited only for the step heading, which can render before the waiver request goes out. It now waits for the request and checks that every waiver request in the all-family flow has no class. It passed 20 of 20 runs locally.

## Deploy notes
No migration. This lets the pending production run deploy #1024 (the "Only N seats left" wording).

## Risk / rollback
Patch-level dependency bump and a test-only change. Revert the PR to undo.
