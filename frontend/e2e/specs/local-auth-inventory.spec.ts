import { readFileSync } from "node:fs";
import path from "node:path";

import { expect, test, type Page, type TestInfo } from "@playwright/test";

const LOCAL_AUTH_ENABLED = process.env.LOCAL_AUTH_E2E === "1";

const PARENT_EMAIL = process.env.LOCAL_AUTH_PARENT_EMAIL ?? "";
const PARENT_PASSWORD = process.env.LOCAL_AUTH_PARENT_PASSWORD ?? "";
const ADMIN_EMAIL = process.env.LOCAL_AUTH_ADMIN_EMAIL ?? "";
const ADMIN_PASSWORD = process.env.LOCAL_AUTH_ADMIN_PASSWORD ?? "";
const COACH_EMAIL = process.env.LOCAL_AUTH_COACH_EMAIL ?? "";
const COACH_PASSWORD = process.env.LOCAL_AUTH_COACH_PASSWORD ?? "";

const BENIGN_CONSOLE_PATTERNS: RegExp[] = [
  /Download the React DevTools/i,
  /Fast Refresh/i,
  /HMR/i,
  /webpack-internal/i,
];

type ManifestRole =
  | "admin"
  | "authenticated"
  | "coach"
  | "parent"
  | "platform"
  | "proxy"
  | "public";

/**
 * Roles this sweep cannot sign in as. `proxy` routes are BFF handlers with no
 * UI; `platform` needs a cross-tenant operator, and the local-auth dataset
 * seeds only admin/coach/parent. Revisit once the seed grows a platform_admin.
 */
const UNSEEDED_ROLES = new Set<ManifestRole>(["proxy", "platform"]);

type ManifestRoute = {
  route: string;
  role: ManifestRole;
};

type DynamicRouteResolution = {
  href: string | null;
  missingEnvVars: string[];
};

type DynamicRouteEnvContract = {
  replacements: [string, string][];
  requiresCoachSessionDate?: boolean;
};

type InventoryManifest = {
  routes: ManifestRoute[];
};

type RuntimeIssueCollector = {
  consoleErrors: string[];
  networkFailures: string[];
};

const INVENTORY_MANIFEST_PATH = path.resolve(
  process.cwd(),
  "../docs/qa/2026-06-28-production-scale-local-inventory-manifest.json",
);

const inventoryManifest = JSON.parse(
  readFileSync(INVENTORY_MANIFEST_PATH, "utf8"),
) as InventoryManifest;

const DIRECT_ROUTE_EXCLUSIONS = new Set(["/post-login"]);

const staticManifestRoutes = inventoryManifest.routes.filter(
  (entry) =>
    !entry.route.includes("[") &&
    !UNSEEDED_ROLES.has(entry.role) &&
    !DIRECT_ROUTE_EXCLUSIONS.has(entry.route),
);

const dynamicManifestRoutes = inventoryManifest.routes.filter(
  (entry) => entry.route.includes("[") && !UNSEEDED_ROLES.has(entry.role),
);

const PUBLIC_ROUTES = routesForRole("public");
const SHARED_AUTH_ROUTES = routesForRole("authenticated");

const DYNAMIC_ROUTE_ENV_CONTRACT: Record<string, DynamicRouteEnvContract> = {
  "/admin/sessions/[id]": {
    replacements: [["[id]", "LOCAL_AUTH_ADMIN_SESSION_ID"]],
  },
  "/admin/sessions/[id]/skill-board": {
    replacements: [["[id]", "LOCAL_AUTH_ADMIN_SESSION_ID"]],
  },
  "/admin/students/[studentId]": {
    replacements: [["[studentId]", "LOCAL_AUTH_ADMIN_STUDENT_ID"]],
  },
  "/admin/students/[studentId]/progress": {
    replacements: [["[studentId]", "LOCAL_AUTH_ADMIN_STUDENT_ID"]],
  },
  "/admin/users/[userId]": {
    replacements: [["[userId]", "LOCAL_AUTH_ADMIN_USER_ID"]],
  },
  "/admin/payouts/[payoutId]": {
    replacements: [["[payoutId]", "LOCAL_AUTH_ADMIN_PAYOUT_ID"]],
  },
  "/admin/registrations/[applicationId]": {
    replacements: [["[applicationId]", "LOCAL_AUTH_ADMIN_APPLICATION_ID"]],
  },
  "/admin/waivers/[waiverId]": {
    replacements: [["[waiverId]", "LOCAL_AUTH_ADMIN_WAIVER_ID"]],
  },
  "/admin/waivers/signatures/[signatureId]": {
    replacements: [["[signatureId]", "LOCAL_AUTH_ADMIN_WAIVER_SIGNATURE_ID"]],
  },
  "/admin/pathway/[programId]": {
    replacements: [["[programId]", "LOCAL_AUTH_ADMIN_PROGRAM_ID"]],
  },
  "/coach/sessions/[id]": {
    replacements: [["[id]", "LOCAL_AUTH_COACH_SESSION_ID"]],
    requiresCoachSessionDate: true,
  },
  "/coach/sessions/[id]/skills": {
    replacements: [["[id]", "LOCAL_AUTH_COACH_OCCURRENCE_ID"]],
    requiresCoachSessionDate: true,
  },
  "/coach/sessions/[id]/progress": {
    replacements: [["[id]", "LOCAL_AUTH_COACH_SESSION_ID"]],
  },
  "/coach/students/[studentId]/passport": {
    replacements: [["[studentId]", "LOCAL_AUTH_COACH_STUDENT_ID"]],
  },
};

test.describe("local authenticated route inventory", () => {
  test.skip(
    !LOCAL_AUTH_ENABLED,
    "Set LOCAL_AUTH_E2E=1 and run against approved local SaaS staging seed data.",
  );

  for (const href of PUBLIC_ROUTES) {
    test(`public route ${href} renders meaningful content`, async ({ page }, testInfo) => {
      const runtimeIssues = collectRuntimeIssues(page);
      await assertRouteRenders(page, href, runtimeIssues, testInfo);
    });
  }

  test.describe("seeded admin route inventory", () => {
    for (const href of routesForRole("admin", SHARED_AUTH_ROUTES)) {
      test(`${href} renders without framework errors`, async ({ page }, testInfo) => {
        const runtimeIssues = collectRuntimeIssues(page);
        await signIn(page, ADMIN_EMAIL, ADMIN_PASSWORD, /\/admin/);
        await assertRouteRenders(page, href, runtimeIssues, testInfo);
      });
    }
  });

  test.describe("seeded coach route inventory", () => {
    for (const href of routesForRole("coach", SHARED_AUTH_ROUTES)) {
      test(`${href} renders without framework errors`, async ({ page }, testInfo) => {
        const runtimeIssues = collectRuntimeIssues(page);
        await signIn(page, COACH_EMAIL, COACH_PASSWORD, /\/coach\/today/);
        await assertRouteRenders(page, href, runtimeIssues, testInfo);
      });
    }
  });

  test.describe("seeded parent route inventory", () => {
    for (const href of routesForRole("parent", SHARED_AUTH_ROUTES)) {
      test(`${href} renders without framework errors`, async ({ page }, testInfo) => {
        const runtimeIssues = collectRuntimeIssues(page);
        await signIn(page, PARENT_EMAIL, PARENT_PASSWORD, /\/parent\/payments/);
        await assertRouteRenders(page, href, runtimeIssues, testInfo);
      });
    }
  });

  test.describe("seeded dynamic route inventory", () => {
    for (const entry of dynamicManifestRoutes) {
      test(`${entry.route} renders with seeded id substitutions`, async ({ page }, testInfo) => {
        const resolved = resolveDynamicRoute(entry.route);
        test.skip(
          !resolved.href,
          `Set ${resolved.missingEnvVars.join(", ")} from approved BLNO seed data.`,
        );

        const runtimeIssues = collectRuntimeIssues(page);
        await signInForRole(page, entry.role);
        await assertRouteRenders(page, resolved.href!, runtimeIssues, testInfo);
      });
    }
  });
});

async function signIn(page: Page, email: string, password: string, homeUrl: RegExp) {
  await page.goto("/login", { waitUntil: "domcontentloaded", timeout: 90_000 });
  await expect(page.getByTestId("login-submit")).toBeEnabled({ timeout: 90_000 });
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(password);
  await page.getByTestId("login-submit").click();
  await expect(page).toHaveURL(homeUrl, { timeout: 90_000 });
}

function collectRuntimeIssues(page: Page): RuntimeIssueCollector {
  const issues: RuntimeIssueCollector = { consoleErrors: [], networkFailures: [] };
  page.on("console", (msg) => {
    if (msg.type() !== "error") return;
    if (BENIGN_CONSOLE_PATTERNS.some((pattern) => pattern.test(msg.text()))) return;
    issues.consoleErrors.push(msg.text());
  });
  page.on("pageerror", (error) => issues.consoleErrors.push(error.message));
  page.on("requestfailed", (request) => {
    if (!isApiUrl(request.url())) return;
    if (request.failure()?.errorText === "net::ERR_ABORTED") return;
    issues.networkFailures.push(
      `${request.method()} ${request.url()} failed: ${request.failure()?.errorText ?? "unknown"}`,
    );
  });
  page.on("response", (response) => {
    if (!isApiUrl(response.url()) || response.status() < 500) return;
    issues.networkFailures.push(
      `${response.request().method()} ${response.url()} returned ${response.status()}`,
    );
  });
  return issues;
}

function routesForRole(role: ManifestRole, extraRoutes: string[] = []): string[] {
  return [
    ...new Set([
      ...staticManifestRoutes
        .filter((entry) => entry.role === role)
        .map((entry) => entry.route),
      ...extraRoutes,
    ]),
  ];
}

function resolveDynamicRoute(route: string): DynamicRouteResolution {
  const replacements = dynamicReplacementsForRoute(route);
  if (replacements.length === 0) {
    return { href: null, missingEnvVars: [`replacement mapping for ${route}`] };
  }

  const missingEnvVars: string[] = [];
  let href = route;
  for (const [token, envName] of replacements) {
    const value = process.env[envName] ?? "";
    if (!value) {
      missingEnvVars.push(envName);
      continue;
    }
    href = href.replace(token, encodeURIComponent(value));
  }

  const dated = withSeededCoachDate(route, href);
  missingEnvVars.push(...dated.missingEnvVars);
  if (dated.href) href = dated.href;

  return missingEnvVars.length > 0 ? { href: null, missingEnvVars } : { href, missingEnvVars };
}

function dynamicReplacementsForRoute(route: string): [string, string][] {
  return DYNAMIC_ROUTE_ENV_CONTRACT[route]?.replacements ?? [];
}

function withSeededCoachDate(route: string, href: string): DynamicRouteResolution {
  if (!DYNAMIC_ROUTE_ENV_CONTRACT[route]?.requiresCoachSessionDate) {
    return { href, missingEnvVars: [] };
  }
  const value = process.env.LOCAL_AUTH_COACH_SESSION_DATE ?? "";
  if (!value) {
    return { href, missingEnvVars: ["LOCAL_AUTH_COACH_SESSION_DATE"] };
  }
  return {
    href: `${href}${href.includes("?") ? "&" : "?"}date=${encodeURIComponent(value)}`,
    missingEnvVars: [],
  };
}

async function signInForRole(page: Page, role: ManifestRole) {
  if (role === "admin") {
    await signIn(page, ADMIN_EMAIL, ADMIN_PASSWORD, /\/admin/);
    return;
  }
  if (role === "coach") {
    await signIn(page, COACH_EMAIL, COACH_PASSWORD, /\/coach\/today/);
    return;
  }
  if (role === "parent" || role === "authenticated") {
    await signIn(page, PARENT_EMAIL, PARENT_PASSWORD, /\/parent\/payments/);
    return;
  }
  throw new Error(`Unsupported dynamic route role: ${role}`);
}

async function assertRouteRenders(
  page: Page,
  href: string,
  runtimeIssues: RuntimeIssueCollector,
  testInfo: TestInfo,
) {
  const priorConsoleErrorCount = runtimeIssues.consoleErrors.length;
  const priorNetworkFailureCount = runtimeIssues.networkFailures.length;
  await page.goto(href, { waitUntil: "domcontentloaded", timeout: 90_000 });
  await expect(page).toHaveURL(new RegExp(`${escapeRegex(href)}(?:[?#].*)?$`), {
    timeout: 90_000,
  });
  await expect(page.locator("body")).not.toContainText("Application error");
  await expect(page.locator("body")).not.toContainText("This page could not be found");
  await expect(page.locator("body")).not.toContainText("Unhandled Runtime Error");
  await expect.poll(
    async () => (await page.locator("body").innerText({ timeout: 30_000 })).trim().length,
    {
      message: `${href} should render beyond the loading shell`,
      timeout: 15_000,
    },
  ).toBeGreaterThan(20);
  const text = await page.locator("body").innerText({ timeout: 30_000 });
  expect(text.trim().length, `${href} should render non-empty content`).toBeGreaterThan(20);
  expect(
    runtimeIssues.consoleErrors.slice(priorConsoleErrorCount),
    `${href} emitted console/page errors`,
  ).toEqual([]);
  expect(
    runtimeIssues.networkFailures.slice(priorNetworkFailureCount),
    `${href} emitted failed API requests`,
  ).toEqual([]);
  await testInfo.attach(`route-${safeAttachmentName(href)}.png`, {
    body: await page.screenshot({ fullPage: true }),
    contentType: "image/png",
  });
}

function escapeRegex(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function isApiUrl(url: string): boolean {
  const parsed = new URL(url);
  return parsed.pathname.startsWith("/api/");
}

function safeAttachmentName(value: string): string {
  const normalized = value.replace(/[^a-z0-9]+/gi, "-").replace(/^-|-$/g, "");
  return normalized || "root";
}
