import { defineConfig, devices } from "@playwright/test";

const baseURL = process.env.LOCAL_AUTH_BASE_URL ?? "http://localhost:3001";

export default defineConfig({
  testDir: "./e2e/specs",
  testMatch: "local-auth-qa.spec.ts",
  timeout: 45 * 1000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: 0,
  reporter: [["list"], ["html", { open: "never" }]],
  use: {
    baseURL,
    trace: "on-first-retry",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
  },
  projects: [
    {
      name: "local-auth-chromium-mobile",
      use: { ...devices["Pixel 7"] },
    },
  ],
});
