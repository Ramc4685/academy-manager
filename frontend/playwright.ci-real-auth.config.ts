import { defineConfig, devices } from "@playwright/test";

const baseURL = assertLocalAuthBaseURL(
  process.env.LOCAL_AUTH_BASE_URL ?? "http://localhost:3001",
);
const evidenceDir =
  process.env.LOCAL_AUTH_EVIDENCE_DIR ?? "/tmp/academy-manager-local/evidence/real-auth-smoke";

function assertLocalAuthBaseURL(rawBaseURL: string): string {
  const url = new URL(rawBaseURL);
  const allowedHosts = new Set(["localhost", "127.0.0.1", "blno.localhost"]);
  if (url.protocol !== "http:" || !allowedHosts.has(url.hostname.toLowerCase())) {
    throw new Error(
      `LOCAL_AUTH_BASE_URL must target local SaaS staging; got ${rawBaseURL}`,
    );
  }
  return rawBaseURL;
}

// Dedicated config for the CI real-auth job: matches only the minimal smoke
// spec, keeping the heavier manual QA sweeps (local-auth-qa / local-auth-inventory,
// see playwright.local-auth.config.ts) out of the CI gate.
export default defineConfig({
  testDir: "./e2e/specs",
  testMatch: ["real-auth-smoke.spec.ts"],
  outputDir: `${evidenceDir}/playwright-artifacts`,
  // Frontend runs via `pnpm dev` (see scripts/local_test_stack.sh) — first
  // hits of /login, /post-login and a persona home each trigger a fresh
  // Next.js dev-server compile, which can push a single test past 45s.
  timeout: 90 * 1000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: [
    ["list"],
    ["json", { outputFile: `${evidenceDir}/playwright-report.json` }],
    ["html", { open: "never", outputFolder: `${evidenceDir}/playwright-html` }],
  ],
  use: {
    baseURL,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
  },
  projects: [
    {
      name: "ci-real-auth-chromium-mobile",
      use: { ...devices["Pixel 7"] },
    },
  ],
});
