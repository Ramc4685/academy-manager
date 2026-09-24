import { realpathSync } from "node:fs";
import { resolve } from "node:path";

import { defineConfig, devices } from "@playwright/test";

import { resolvePort } from "./lib/worktree-port";

// Per-worktree default port (#522): a fixed 3001 default made concurrent
// worktrees contend — CI=true runs failed to bind (mass fake regressions) and
// plain local runs silently reused ANOTHER worktree's dev server. The default
// now hashes the repo root into 3001-3999 so each worktree gets a stable,
// distinct port (also under CI=true — the pre-push gate sets it locally).
// PLAYWRIGHT_PORT still overrides.
const PORT = resolvePort({
  override: process.env.PLAYWRIGHT_PORT,
  repoRoot: realpathSync(resolve(__dirname, "..")),
});

// The public academy page (app/page.tsx on a tenant host) is server-rendered,
// so its backend read cannot be stubbed with browser-side page.route. A tiny
// stub server answers it instead (e2e/fixtures/public-academy-stub.mjs) and
// the Next dev server's BFF_API_ORIGIN points at it. Everything the browser
// fetches is still stubbed by mock-api.ts before it reaches Next; any other
// path the stub gets answers 502, like the dead backend it replaces.
const PUBLIC_ACADEMY_STUB_PORT = String(Number(PORT) + 3000);
const E2E_PROXY_SECRET = "e2e-proxy-secret";
// Workers inherit this, so public-tenant-page.spec.ts can read what the stub saw.
process.env.PUBLIC_ACADEMY_STUB_PORT = PUBLIC_ACADEMY_STUB_PORT;
process.env.E2E_PROXY_SECRET = E2E_PROXY_SECRET;

// Axe accessibility specs (D11) run only in the a11y-chromium project.
const A11Y_SPECS = /a11y-[^/]*\.spec\.ts$/;

export default defineConfig({
  testDir: "./e2e/specs",
  timeout: 30 * 1000,
  expect: { timeout: 5_000 },
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  // Fail the run when any test was flaky (failed-then-passed-on-retry).
  // A flaky test is a code smell, not a clean pass — usually a race in
  // the page that lets the test win or lose based on timing. Letting CI
  // succeed silently on flakies hides real bugs (see commit 28d1a2b's
  // post-merge debrief: the admin/students webkit crash flaked through
  // PR review then hard-failed on main). Available since Playwright 1.49.
  failOnFlakyTests: !!process.env.CI,
  // Two workers in CI: each CI job runs one browser project against its own
  // fresh `next dev` server, and the mobile project (~109 tests) took ~6 min
  // on one worker. Local runs keep Playwright's default (half the cores).
  workers: process.env.CI ? 2 : undefined,
  reporter: [["list"], ["html", { open: "never" }]],
  use: {
    baseURL: `http://localhost:${PORT}`,
    trace: "on-first-retry",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
  },
  webServer: [
    {
      command: "node e2e/fixtures/public-academy-stub.mjs",
      url: `http://127.0.0.1:${PUBLIC_ACADEMY_STUB_PORT}/__health`,
      reuseExistingServer: !process.env.CI,
      timeout: 30_000,
      env: { PUBLIC_ACADEMY_STUB_PORT },
    },
    {
      // `pnpm dev` runs Turbopack (see package.json). With the webpack dev
      // server, the first request for a not-yet-compiled route pushed an HMR
      // update to the already-open page that React Refresh could not apply, so
      // `next dev` did a full `location.reload()` of the CURRENT url ~1.5s into
      // the request. That reload cancelled the in-flight document load and
      // Playwright failed the step with "Navigation to <deep route> is
      // interrupted by another navigation to <the page we came from>" (#650,
      // and deterministically on webkit-mobile in admin-shell.spec.ts). It is a
      // dev-server artifact, not app behaviour: nothing in the shell navigates.
      // Turbopack applies those updates without a full reload.
      //
      // Launch next directly, not via `pnpm dev`. pnpm 11.27.1 (2026-09-20)
      // changed `pnpm run` to forward signals to the script and then WAIT for
      // it to finish shutting down; Playwright's webServer teardown killed
      // pnpm, pnpm waited on `next dev`, the stdio pipes never closed, and
      // every CI e2e job hung after its last test until timeout-minutes
      // (CI resolves the floating `pnpm/action-setup` `version: 11`, so the
      // bump arrived without a lockfile change). Same flags as `pnpm dev`.
      command: "node_modules/.bin/next dev --turbopack -p ${PORT}",
      url: `http://localhost:${PORT}/login`,
      reuseExistingServer: !process.env.CI,
      // Cold `next dev` in a fresh worktree can exceed 60s before /login responds.
      timeout: 180_000,
      env: {
        PORT,
        NEXT_PUBLIC_E2E_AUTH_BYPASS: "1",
        // Deterministic Firebase web config for the google-signin-mode spec.
        // CI has no frontend/.env, and the local .env points at the auth
        // emulator; OS env wins over .env files in next dev, so these pin the
        // values in both places. The fake authDomain never resolves — the spec
        // intercepts the /__/auth/ navigation before it hits the network.
        NEXT_PUBLIC_FIREBASE_API_KEY: "e2e-fake-api-key",
        NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN: "e2e-firebase-auth.example.com",
        NEXT_PUBLIC_FIREBASE_PROJECT_ID: "e2e-project",
        NEXT_PUBLIC_FIREBASE_APP_ID: "1:0:web:e2e",
        NEXT_PUBLIC_FIREBASE_AUTH_EMULATOR_HOST: "",
        BFF_API_ORIGIN: `http://127.0.0.1:${PUBLIC_ACADEMY_STUB_PORT}`,
        BFF_PROXY_SHARED_SECRET: E2E_PROXY_SECRET,
      },
    },
  ],
  projects: [
    {
      name: "chromium-mobile",
      use: { ...devices["Pixel 7"] },
      testIgnore: A11Y_SPECS,
    },
    {
      name: "webkit-mobile",
      use: { ...devices["iPhone 14"] },
      testIgnore: A11Y_SPECS,
    },
    // Desktop viewport so the admin lg: sidebar branch (the primary admin
    // navigation on real screens) is exercised end-to-end. Scoped via
    // testMatch to a few admin specs so CI wall-time grows by minutes,
    // not double (workers=2 in CI).
    {
      name: "chromium-desktop",
      use: {
        ...devices["Desktop Chrome"],
        viewport: { width: 1280, height: 800 },
      },
      // month-close joins the list for #862: its collapsible groups default
      // open on desktop and closed on a phone, so the default only gets
      // exercised by running the spec under both viewports. messages joins
      // for #864, where a phone replaces the thread list with the open
      // thread and a desktop shows both at once. family-billing joins for
      // #890: the invoice row's direct-vs-More-menu split and the "one home
      // per money action" rule are a 1280px claim, and the row renders a
      // different branch (table vs PhoneListRow) on each viewport.
      // families-index joins for the People CRM Families view: its sortable
      // headers and money column exist only in the desktop table.
      // family-record joins for the People CRM family record: the child drawer
      // is a side panel on a desktop and full width on a phone.
      // public-page-settings joins for Lane B5: the per-class list is a
      // wide table that scrolls sideways on a phone and fits on a desktop.
      testMatch:
        /admin-(shell|students|registrations|level-ups-lifecycle|month-close|messages|family-billing|families-index|family-record|public-page-settings)\.spec\.ts/,
    },
    // D11 axe gate: chromium only, its own CI job in nightly-e2e.yml (nightly,
    // and on PRs that touch frontend/components/** or the a11y specs). The
    // per-PR mobile projects above ignore these specs.
    {
      name: "a11y-chromium",
      use: { ...devices["Pixel 7"] },
      testMatch: A11Y_SPECS,
    },
  ],
});
