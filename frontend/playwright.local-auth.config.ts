import { defineConfig, devices } from "@playwright/test";

const baseURL = assertLocalAuthBaseURL(
  process.env.LOCAL_AUTH_BASE_URL ?? "http://blno.localhost:3000",
);
const evidenceDir =
  process.env.LOCAL_AUTH_EVIDENCE_DIR ??
  "/tmp/academy-manager-local/evidence/20260628-production-scale-audit";

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

export default defineConfig({
  testDir: "./e2e/specs",
  testMatch: ["local-auth-qa.spec.ts", "local-auth-inventory.spec.ts"],
  outputDir: `${evidenceDir}/playwright-artifacts`,
  timeout: 45 * 1000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: 0,
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
      name: "local-auth-chromium-mobile",
      use: { ...devices["Pixel 7"] },
    },
  ],
});
