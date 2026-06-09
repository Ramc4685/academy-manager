import { defineConfig, devices } from "@playwright/test";

const PORT = process.env.PLAYWRIGHT_PORT ?? "3001";

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
    timeout: 60_000,
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
  ],
});
