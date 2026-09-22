# e2e-webserver-direct-next

PR: #903

## What changed
Playwright's e2e webServer now launches `next dev` directly from `node_modules/.bin` instead of through `pnpm dev`. pnpm 11.27.1 changed `pnpm run` to forward signals and wait for the script to shut down, which left every CI e2e job hanging after its last test until `timeout-minutes`. No application code or user-facing behaviour changes.

## Deploy notes
None. CI/test infrastructure only; no migrations, env vars or manual steps.

## Risk / rollback
Risk is limited to the e2e harness: if the direct command failed to start, e2e jobs would fail fast at webServer startup rather than hang. Roll back by restoring `command: "pnpm dev"` in `frontend/playwright.config.ts` (and pinning pnpm below 11.27.1 in CI).
