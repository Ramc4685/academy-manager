# ci-webkit-coach-passport-production-flow

## Current State

Status: active

## Problem

Fix WebKit mobile flake blocking production workflow, then verify production deploy and Fly migrations

## Changed Files

- None recorded yet.

## Log

- 2026-06-19T14:12:43 main/NA: Task ledger created.
- 2026-06-19T14:13:34 main/working: Kickoff complete in isolated worktree feat/ci-webkit-coach-passport-production-flow from origin/main. CI run 27842439225 failed Production Frontend E2E WebKit on pnpm exec playwright test --project=webkit-mobile: coach-day-hub-passport.spec.ts timed out waiting for coach-session-skills after clicking Open skill updates; retry passed, causing flaky failure. Required docs, workflow, Fly config, coach active ledger, and production migration readiness ledger read before edits.
- 2026-06-19T14:41:07 main/working: Changed files: frontend/e2e/specs/coach-day-hub-passport.spec.ts waits for the skills URL after Open skill updates; frontend/e2e/specs/admin-session-creation-ui.spec.ts uses a heading locator for Replacement coaches; frontend/e2e/specs/saas-launch-route-matrix.spec.ts marks admin route-mount smoke tests slow and waits only for domcontentloaded; test_result.md and this active ledger updated.
## Verification

- No verification recorded yet.
- 2026-06-19T14:16:25: Setup/repro evidence: cd frontend && pnpm install --frozen-lockfile passed; pnpm exec playwright install --with-deps webkit passed; pnpm exec playwright test e2e/specs/coach-day-hub-passport.spec.ts --project=webkit-mobile --repeat-each=3 passed 3/3; CI=1 pnpm exec playwright test e2e/specs/coach-day-hub-passport.spec.ts --project=webkit-mobile --repeat-each=5 passed 5/5. Downloaded GitHub artifact playwright-report-webkit for run 27842439225; error-context shows failure page still on /coach/dashboard with Open skill updates link visible when coach-session-skills assertion timed out.
- 2026-06-19T14:17:23: Post-fix focused verification: cd frontend && CI=1 pnpm exec playwright test e2e/specs/coach-day-hub-passport.spec.ts --project=webkit-mobile --repeat-each=10 => 10 passed in 36.3s. Warnings observed: existing NO_COLOR/FORCE_COLOR and Fast Refresh full reload messages.
- 2026-06-19T14:19:44: Full WebKit after coach spec fix: cd frontend && CI=1 pnpm exec playwright test --project=webkit-mobile => original coach-day-hub-passport test passed at slot 41, but suite exited 1 due a new flaky test: qa-defects.spec.ts wrong-role coach redirects explain access denial expected /parent/payments?access_denied=coach, first run reached /login after /coach/sessions, retry passed; 86 passed, 15 skipped, 1 flaky.
- 2026-06-19T14:23:55: Full WebKit verification rerun: cd frontend && CI=1 pnpm exec playwright test --project=webkit-mobile => 87 passed, 15 skipped in 2.1m. The fixed coach-day-hub-passport test passed at slot 41 under the same Fast Refresh full-reload condition; the previously observed qa-defects wrong-role coach transient also passed on this rerun. Prior failed full-suite run is recorded as an observed unrelated transient, not patched because isolated 20x and full rerun passed.
- 2026-06-19T14:24:53: Frontend static verification: cd frontend && pnpm audit --audit-level=high => exit 0 with 1 low and 4 moderate vulnerabilities, no high; pnpm typecheck => passed; pnpm lint => exit 0 with 5 existing unrelated warnings; pnpm build => passed, same existing lint warnings plus Next/Serwist/tailwind module-type warnings.
- 2026-06-19T14:26:21: Corrected worktree focused verification: cd frontend && CI=1 pnpm exec playwright test e2e/specs/coach-day-hub-passport.spec.ts --project=webkit-mobile --repeat-each=10 => 10 passed in 37.6s against the worktree diff. Existing warnings: NO_COLOR/FORCE_COLOR, Fast Refresh full reload, module.register/tailwind module-type.
- 2026-06-19T14:29:13: Corrected worktree full WebKit rerun: cd frontend && CI=1 pnpm exec playwright test --project=webkit-mobile => coach-day-hub-passport passed, but suite exited 1 with two unrelated flaky tests that passed on retry: admin-session-creation-ui replacement coach test strict text locator matched heading plus empty-state paragraph; saas-launch-route-matrix admin payouts timed out waiting for page.goto load. Applying narrow E2E locator/synchronization fixes for those before rerunning.
- 2026-06-19T14:30:07: Additional focused WebKit verification: cd frontend && CI=1 pnpm exec playwright test e2e/specs/admin-session-creation-ui.spec.ts --project=webkit-mobile -g 'session detail adds replacement coach' --repeat-each=10 => 10 passed; CI=1 pnpm exec playwright test e2e/specs/saas-launch-route-matrix.spec.ts --project=webkit-mobile -g 'admin route mounts: payouts' --repeat-each=10 => 10 passed.
- 2026-06-19T14:32:50: Full WebKit rerun after route matrix domcontentloaded change still exited 1: admin messages route matrix timed out waiting for domcontentloaded at 30s and passed on retry. Root cause is cold Next dev route compilation in the route-mount smoke matrix; adding test.slow() to admin route matrix tests before rerun.
- 2026-06-19T14:33:19: Route matrix slow-marker focused verification: cd frontend && CI=1 pnpm exec playwright test e2e/specs/saas-launch-route-matrix.spec.ts --project=webkit-mobile -g 'admin route mounts: messages' --repeat-each=10 => 10 passed.
- 2026-06-19T14:40:51: Final local checks after all test edits: cd frontend && pnpm audit --audit-level=high => exit 0 with 1 low/4 moderate; pnpm typecheck => passed; pnpm lint => exit 0 with same 5 existing unrelated warnings; pnpm build => passed with same existing warnings; git diff --check => passed. Local full WebKit suite became unreliable after repeated runs and was interrupted/stopped due unrelated dev-server stalls; authoritative fresh full-suite validation will be GitHub Production/PR CI.
- 2026-06-19T14:55:41: scripts/dev/pre-push-checks.sh --full failed in pnpm e2e: chromium admin-shell logout did not reach /login, chromium coach-day-hub-passport had navigation races to passport/teaching plan, and webkit qa-defects wrong-role coach was flaky; holding push until focused fixes are verified.
- 2026-06-19T15:04:22: Focused fixes verified: coach-day-hub-passport passes 10x on webkit-mobile and 10x on chromium-mobile after following the real session-detail Skills link; admin-shell logout passes 10x on chromium-mobile after waiting for shell hydration; qa-defects wrong-role coach passes 10x on webkit-mobile after auth redirect cleanup/fallback timing changes.
- 2026-06-19T15:04:36: pnpm typecheck passed after auth hook and E2E spec changes.
- 2026-06-19T15:09:57: scripts/dev/pre-push-checks.sh --full passed: backend ruff format/check, backend pytest v2/tests, frontend node unit tests, pnpm typecheck, pnpm lint, and full pnpm e2e.
## Reusable Lessons

- None recorded yet.
