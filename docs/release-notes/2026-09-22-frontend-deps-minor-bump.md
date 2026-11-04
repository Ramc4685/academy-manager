# frontend-deps-minor-bump

PR: #912

## What changed

- Frontend dependency bumps, minors and patches only. This replaces dependabot #833, which bundled four major-version jumps (fullcalendar 7, typescript 6, eslint 10, vitest 5) with the routine updates and was closed. Fullcalendar 7 stays parked under #492; typescript stays 5.9.3, eslint 9.13.0, vitest and @vitest/coverage-v8 ^4.1.11.
- Bumped: @sentry/browser 10.74.0, firebase 12.19.0, lucide-react 1.46.0, next 16.3.5, react and react-dom 19.3.0, tailwind-merge 3.7.0, web-vitals 6.2.2, @opennextjs/cloudflare ^1.20.6, @playwright/test 1.63.0, size-limit and @size-limit/preset-app 13.1.1, @types/node 26.5.1, @types/react and @types/react-dom 19.3.0, autoprefixer 10.6.0, eslint-config-next 16.3.5, postcss 8.5.28, wrangler ^4.131.2 (lockfile resolves 4.136.3).
- No source changes. `frontend/pnpm-lock.yaml` re-resolved only the bumped packages and their transitives. The build stays `next build --webpack`.
- Verified locally on Node 22: `pnpm typecheck`, `pnpm lint` (0 errors), `pnpm build`, 195 node unit tests, 867 vitest tests, and the full pre-push gate (backend pytest included) all pass.

## Deploy notes

None. Frontend-only dependency change; no migrations, no environment or secret changes. The Fly image rebuilds with the new lockfile on the normal deploy.

## Risk / rollback

Low. React 19.3 and Next 16.3.5 are minor/patch releases and every local gate passed, but the Playwright e2e suites run in CI rather than locally for this PR, so watch the CI Gate. Rollback is a plain revert of the two commits on this PR; nothing persists outside the built image.
