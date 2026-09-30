# Unblock the production run: urllib3 2.8.0, PyJWT 2.15.0, Next.js 16.3.8 and a class-first e2e race

PR: #1025

## What changed
- Backend: `urllib3` bumped from 2.7.0 to 2.8.0 for CVE-2026-97687, CVE-2026-97688 and CVE-2026-97689. The dependency audit was failing the production run.
- Backend: `PyJWT` bumped from 2.14.0 to 2.15.0 for CVE-2026-101918, which was published while this PR was open. The backend does not import it directly; it comes in through firebase-admin and google-auth.
- Frontend: `next` and `eslint-config-next` bumped from 16.3.5 to 16.3.8 for GHSA-vcvr-r3jv-pc5j, a critical remote-code-execution bug in `next/og` ImageResponse (patched in 16.3.6). It was also published while this PR was open. The build stays on `next build --webpack`.
- E2E: `parent-onboarding-class-first.spec.ts` waited only for the step heading, which can render before the waiver request goes out. It now waits for the request and checks that every waiver request in the all-family flow has no class. It passed 20 of 20 runs locally.

## Deploy notes
No migration. This lets the pending production run deploy #1024 (the "Only N seats left" wording).

## Risk / rollback
Minor dependency bumps and a test-only change. Revert the PR to undo.
