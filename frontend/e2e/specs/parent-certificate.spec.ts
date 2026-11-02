/**
 * Parent level certificate: the screen the evening win email's "See the
 * certificate" button opens, and its print layout.
 *
 * Mocks the v2 BFF at the Playwright route layer (synthetic data only), like
 * parent-home.spec.ts. Runs on the mobile projects; the one-page PDF check
 * needs Chromium's page.pdf().
 */

import { test, expect } from "../fixtures/mock-api";
import type { Page, Route } from "@playwright/test";

const LOGO_URL = "https://logo.example.test/aces.svg";
const LOGO_SVG =
  '<svg xmlns="http://www.w3.org/2000/svg" width="160" height="64" viewBox="0 0 160 64">' +
  '<rect width="160" height="64" rx="10" fill="#0f766e"/>' +
  '<text x="80" y="41" text-anchor="middle" font-family="sans-serif" font-size="24" ' +
  'font-weight="700" fill="#fff">ACES</text></svg>';

async function json(route: Route, body: unknown, status = 200): Promise<void> {
  await route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
}

async function stubGet(page: Page, pattern: string, body: unknown): Promise<void> {
  await page.route(pattern, async (route: Route) => {
    if (route.request().method() !== "GET") return route.fallback();
    return json(route, body);
  });
}

const DETAIL = {
  certificate: {
    cert_id: "cert-1",
    student_id: "st-1",
    cert_number: "ACE-L1-ST1-1793452800000",
    student_name: "Ava Kim",
    level_name: "Grip and Control",
    program_name: "Badminton Pathway",
    // 8:30 PM in Chicago on Oct 30 — already Oct 31 in UTC.
    completed_at: "2026-10-31T01:30:00",
    issued_at: "2026-10-31T01:30:00",
  },
  level_number: 1,
  skills: ["Thumb grip", "V grip", "Grip change", "Ready position", "Shuttle control"],
  next_level: { level_id: "l2", name: "Net and Movement", number: 2 },
  levels: [
    { name: "Grip and Control", color: "#F8FAFC" },
    { name: "Net and Movement", color: "#FACC15" },
    { name: "Rally and Attack", color: "#FB923C" },
  ],
};

async function stubCertificate(page: Page): Promise<void> {
  await stubGet(page, "**/api/v2/me", {
    user_id: "user-parent-e2e",
    email: "parent@example.com",
    academy_id: "academy-e2e",
    roles: ["parent"],
  });
  await stubGet(page, "**/api/v2/parent/messages", { messages: [] });
  await stubGet(page, "**/api/v2/parent/academy", {
    display_name: "Aces Academy",
    timezone: "America/Chicago",
    contact_email: null,
    contact_phone: null,
    hours_text: null,
    address: null,
    logo_url: LOGO_URL,
    brand_color: "#0f766e",
  });
  await page.route(LOGO_URL, (route) =>
    route.fulfill({ status: 200, contentType: "image/svg+xml", body: LOGO_SVG }),
  );
  await page.route("**/api/v2/parent/students/*/certificates/*", async (route: Route) => {
    if (route.request().method() !== "GET") return route.fallback();
    // The BFF answers 404 for anything but the parent's own child's certificate.
    if (!route.request().url().includes("/students/st-1/certificates/cert-1")) {
      return json(route, { detail: "Certificate not found" }, 404);
    }
    return json(route, DETAIL);
  });
}

test.describe("parent level certificate", () => {
  test("shows the certificate with print and share actions", async ({ page }, testInfo) => {
    await stubCertificate(page);
    await page.goto("/parent/progress/certificates/cert-1?child=st-1");

    const screen = page.getByTestId("parent-certificate");
    await expect(screen.getByRole("heading", { name: "Level 1 certificate" })).toBeVisible();
    await expect(screen.getByText("Ava finished Grip and Control")).toBeVisible();
    await expect(screen.getByText("All 5 skills mastered on October 30, 2026.")).toBeVisible();

    const cert = page.getByTestId("level-certificate");
    await expect(cert.getByText("Ava Kim")).toBeVisible();
    await expect(cert.getByText("Level 1 · Grip and Control")).toBeVisible();
    await expect(cert.getByText("Ready position")).toBeVisible();
    await expect(cert.getByText("ACE-L1-ST1-1793452800000")).toBeVisible();
    await expect(cert.getByRole("img", { name: "Aces Academy" })).toBeVisible();

    await expect(screen.getByRole("button", { name: "Print or save as PDF" })).toBeVisible();
    await expect(screen.getByRole("button", { name: "Share with family" })).toBeVisible();
    await expect(screen.getByRole("link", { name: /Up next/ })).toHaveAttribute(
      "href",
      "/parent/progress?child=st-1",
    );

    // The preview must fit a phone: no sideways scroll.
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow).toBeLessThanOrEqual(0);
    await page.screenshot({ path: testInfo.outputPath("certificate-screen.png"), fullPage: true });
  });

  test("prints only the certificate, on one Letter landscape page", async ({
    page,
    browserName,
  }, testInfo) => {
    test.skip(browserName !== "chromium", "page.pdf() is Chromium-only");
    await stubCertificate(page);
    await page.goto("/parent/progress/certificates/cert-1?child=st-1");
    await expect(page.getByTestId("level-certificate").getByText("Ava Kim")).toBeVisible();

    await page.emulateMedia({ media: "print" });
    await expect(page.getByRole("button", { name: "Print or save as PDF" })).toBeHidden();
    await expect(page.getByTestId("level-certificate").getByText("Ava Kim")).toBeVisible();

    const pdf = await page.pdf({ preferCSSPageSize: true, printBackground: true });
    const pages = pdf.toString("latin1").match(/\/Type\s*\/Page[^s]/g) ?? [];
    expect(pages).toHaveLength(1);
    await testInfo.attach("certificate.pdf", { body: pdf, contentType: "application/pdf" });
    await page.setViewportSize({ width: 1056, height: 816 });
    await page.screenshot({ path: testInfo.outputPath("certificate-print.png") });
  });

  test("another child's certificate shows a not-found notice", async ({ page }) => {
    await stubCertificate(page);
    await page.goto("/parent/progress/certificates/cert-1?child=someone-else");
    await expect(page.getByText("We couldn't find this certificate.")).toBeVisible();
    await expect(page.getByTestId("level-certificate")).toHaveCount(0);
  });
});
