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
  webServer: {
    command: "pnpm dev",
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
    },
  },
  projects: [
    {
      name: "chromium-mobile",
      use: { ...devices["Pixel 7"] },
    },
    {
      name: "webkit-mobile",
      use: { ...devices["iPhone 14"] },
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
      testMatch: /admin-(shell|students|registrations)\.spec\.ts/,
    },
  ],
});
