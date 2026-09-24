/**
 * D11: axe accessibility gate.
 *
 * Runs axe-core (WCAG 2.0 A + AA tags, colour contrast included) over one
 * representative screen per surface, all under the same browser-side stubs
 * the other specs use, and fails on any violation whose impact is "serious"
 * or "critical". Runs in its own Playwright project (a11y-chromium), which
 * the nightly workflow runs as its own job; the per-PR mobile/desktop
 * projects ignore this file.
 *
 * Known violations live in ALLOWLIST: one entry per rule id + CSS selector,
 * each linked to an issue. The list only shrinks. An entry whose violation
 * no longer appears fails the run too, so a fix has to delete its entry and
 * the gate ratchets instead of silently carrying dead exemptions.
 */

import AxeBuilder from "@axe-core/playwright";
import type { Page, Route } from "@playwright/test";

import { test, expect } from "../fixtures/mock-api";
import {
  stubCoachMessages,
  stubParentAcademy,
  stubParentMessages,
  stubParentProfile,
} from "../fixtures/saas-stubs";

type Surface = "public" | "parent-home" | "admin-dashboard" | "coach-today";

interface AllowlistEntry {
  surface: Surface;
  rule: string;
  /** axe's node target, joined with " > " for shadow/iframe hops. */
  target: string;
  issue: string;
}

const ALLOWLIST: readonly AllowlistEntry[] = [];

const BLOCKING_IMPACTS = new Set(["serious", "critical"]);

interface Finding {
  rule: string;
  impact: string;
  target: string;
  summary: string;
}

async function waitForFiniteAnimations(page: Page): Promise<void> {
  // Colour contrast read mid-fade is a coin flip. Wait for every finite
  // animation to finish; spinners and other infinite loops are ignored.
  await page.waitForFunction(() =>
    document.getAnimations().every((animation) => {
      const timing = animation.effect?.getComputedTiming();
      const finite = timing?.iterations !== Infinity;
      return !finite || animation.playState !== "running";
    }),
  );
}

async function blockingFindings(page: Page): Promise<Finding[]> {
  await waitForFiniteAnimations(page);
  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa"])
    .analyze();
  const findings: Finding[] = [];
  for (const violation of results.violations) {
    if (!BLOCKING_IMPACTS.has(violation.impact ?? "")) continue;
    for (const node of violation.nodes) {
      findings.push({
        rule: violation.id,
        impact: violation.impact ?? "",
        target: node.target.map(String).join(" > "),
        summary: (node.failureSummary ?? violation.help).replace(/\s+/g, " ").trim(),
      });
    }
  }
  return findings;
}

async function expectNoBlockingViolations(page: Page, surface: Surface): Promise<void> {
  const findings = await blockingFindings(page);
  const allowed = ALLOWLIST.filter((entry) => entry.surface === surface);
  const isAllowed = (f: Finding) =>
    allowed.some((entry) => entry.rule === f.rule && entry.target === f.target);

  const unexpected = findings.filter((f) => !isAllowed(f));
  expect(
    unexpected,
    `axe found ${unexpected.length} serious/critical violation(s) on ${surface}:\n` +
      unexpected
        .map((f) => `  [${f.impact}] ${f.rule} at ${f.target}\n    ${f.summary}`)
        .join("\n"),
  ).toEqual([]);

  const stale = allowed.filter(
    (entry) => !findings.some((f) => f.rule === entry.rule && f.target === entry.target),
  );
  expect(
    stale,
    `allowlisted violation(s) on ${surface} no longer occur; delete the entry:\n` +
      stale.map((e) => `  ${e.rule} at ${e.target} (${e.issue})`).join("\n"),
  ).toEqual([]);
}

function fulfillJson(route: Route, body: unknown): Promise<void> {
  return route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify(body),
  });
}

async function stubGet(page: Page, pattern: string | RegExp, body: unknown): Promise<void> {
  await page.route(pattern, (route) => {
    if (route.request().method() !== "GET") return route.fallback();
    return fulfillJson(route, body);
  });
}

async function stubMe(page: Page, roles: string[], userId: string): Promise<void> {
  await stubGet(page, "**/api/v2/me", {
    user_id: userId,
    email: `${userId}@example.com`,
    academy_id: "academy-e2e",
    roles,
  });
  await stubGet(page, "**/api/v2/me/memberships", {
    memberships: [
      {
        academy_id: "academy-e2e",
        academy_name: "Academy E2E",
        academy_slug: "academy-e2e",
        roles,
        status: "active",
        is_default: true,
      },
    ],
    active_academy_id: "academy-e2e",
  });
}

test.describe("axe: public academy page", () => {
  test.use({
    userAgent: "Mozilla/5.0 (Playwright e2e) cm-e2e-public-fixture/published",
  });

  test("has no serious or critical WCAG A/AA violations", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByTestId("public-academy-page")).toBeVisible();
    await expectNoBlockingViolations(page, "public");
  });
});

test.describe("axe: parent home", () => {
  test("has no serious or critical WCAG A/AA violations", async ({ page }) => {
    await stubMe(page, ["parent"], "user-parent-e2e");
    await stubParentProfile(page);
    await stubParentMessages(page);
    await stubParentAcademy(page);
    await stubGet(page, "**/api/v2/parent/enrollments", { enrollments: [] });
    await stubGet(page, "**/api/v2/parent/attendance", { records: [] });
    await stubGet(page, "**/api/v2/parent/progress", { notes: [] });
    await stubGet(page, "**/api/v2/parent/payments", { payments: [] });
    await stubGet(page, "**/api/v2/parent/invoices", { invoices: [] });
    await stubGet(page, "**/api/v2/parent/credits", { balance_cents: 0, credits: [] });
    await stubGet(page, "**/api/v2/parent/waivers/current", {
      required: false,
      waiver_template_id: null,
      title: null,
      version: null,
      body: null,
      students: [],
    });
    // A balance due, so the Pay banner (the parent's money call to action)
    // is part of the scan, not just the empty state.
    await stubGet(page, "**/api/v2/parent/home", {
      children: [
        {
          student_id: "st-1",
          full_name: "Ava Sample",
          next_session: {
            occurrence_id: "occ-1",
            session_id: "sess-1",
            session_title: "Junior Beginners",
            location: "Court 2",
            start_at: "2026-09-10T23:00:00Z",
            end_at: "2026-09-11T00:00:00Z",
            coach_name: null,
          },
          attendance_this_month: { present: 6, total: 7 },
          latest_milestone: { kind: "skill", label: "Backhand lift", at: "2026-08-20T14:00:00Z" },
        },
      ],
      balance: {
        amount_due_cents: 12000,
        currency: "usd",
        due_date: "2026-09-12",
        open_invoice_count: 1,
        payment_failed: false,
      },
      month_label: "September",
      timezone: "America/Chicago",
    });

    await page.goto("/parent/dashboard");
    await expect(page.getByTestId("parent-dashboard")).toBeVisible();
    await expect(page.getByTestId("parent-balance-banner")).toBeVisible();
    await expectNoBlockingViolations(page, "parent-home");
  });
});

test.describe("axe: admin dashboard", () => {
  test("has no serious or critical WCAG A/AA violations", async ({ page }) => {
    await stubMe(page, ["admin", "owner"], "user-admin-e2e");
    // Catch-all first: later, more specific stubs win (LIFO).
    await stubGet(page, "**/api/v2/admin/**", {});
    await stubGet(page, "**/api/v2/admin/sessions*", { sessions: [] });
    await stubGet(page, "**/api/v2/admin/students*", { students: [] });
    await stubGet(page, "**/api/v2/admin/inbox/counts", { counts: {}, total: 0 });
    await stubGet(page, "**/api/v2/admin/messages*", { messages: [] });
    await stubGet(page, "**/api/v2/admin/dashboard/attention*", {
      items: [
        {
          attention_id: "waiver-status",
          kind: "waivers",
          title: "Waivers need review",
          detail: "2 pending, 1 outdated.",
          severity: "medium",
          href: "/admin/waivers",
          count: 3,
        },
      ],
    });
    await stubGet(page, /\/api\/v2\/admin\/academy(?:\?.*)?$/, {
      academy_id: "academy-e2e",
      display_name: "Academy E2E",
      timezone: "UTC",
      contact_email: null,
      contact_phone: null,
      hours_text: null,
      address: null,
    });

    await page.goto("/admin");
    await expect(page.getByTestId("admin-dashboard")).toBeVisible();
    await expectNoBlockingViolations(page, "admin-dashboard");
  });
});

test.describe("axe: coach today", () => {
  test("has no serious or critical WCAG A/AA violations", async ({ page, mock }) => {
    void mock; // the mock-api fixture stubs the whole coach surface
    await stubCoachMessages(page);
    await page.goto("/coach/today");
    await expect(page.getByTestId("coach-today")).toBeVisible();
    await expect(page.getByTestId("session-s-today-1")).toBeVisible();
    await expectNoBlockingViolations(page, "coach-today");
  });
});

test.describe("axe gate self-check", () => {
  test.use({
    userAgent: "Mozilla/5.0 (Playwright e2e) cm-e2e-public-fixture/published",
  });

  test("an injected low-contrast element is reported as a blocking finding", async ({
    page,
  }) => {
    await page.goto("/");
    await expect(page.getByTestId("public-academy-page")).toBeVisible();
    await page.evaluate(() => {
      const probe = document.createElement("p");
      probe.id = "a11y-gate-probe";
      probe.textContent = "Low contrast probe";
      // #aaaaaa on white is 2.32:1, well under the 4.5:1 AA floor.
      probe.style.cssText = "color:#aaaaaa;background:#ffffff;font-size:14px";
      document.body.append(probe);
    });
    await expect(page.locator("#a11y-gate-probe")).toBeVisible();
    const findings = await blockingFindings(page);
    expect(findings).toContainEqual(
      expect.objectContaining({ rule: "color-contrast", target: "#a11y-gate-probe" }),
    );
  });
});
