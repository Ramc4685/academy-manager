/**
 * Lane B3: the public academy page at `/` on a tenant host.
 *
 * The page is server-rendered, so its backend read is answered by the stub
 * server playwright.config.ts starts (e2e/fixtures/public-academy-stub.mjs),
 * not by browser-side page.route. Each describe block picks a fixture from
 * e2e/fixtures/public-academy-pages.json through its user agent. The
 * academy is fictional ("Riverside Shuttle Club").
 *
 * localhost is not a product host (lib/public-page/host.ts), so `/` here is
 * a tenant host; the product-host branch is covered by host.test.ts.
 */

import { expect, test, type Page } from "@playwright/test";

const STUB = `http://127.0.0.1:${process.env.PUBLIC_ACADEMY_STUB_PORT}`;

function fixtureAgent(name: string): string {
  return `Mozilla/5.0 (Playwright e2e) cm-e2e-public-fixture/${name}`;
}

async function robotsMeta(page: Page): Promise<string | null> {
  return page.locator('meta[name="robots"]').first().getAttribute("content");
}

test.describe("published page", () => {
  test.use({ userAgent: fixtureAgent("published") });

  test("renders hero, programs, price and seat bands with brand buttons", async ({ page }) => {
    const response = await page.goto("/");
    expect(response?.status()).toBe(200);

    await expect(page.getByTestId("public-academy-page")).toBeVisible();
    await expect(page.getByRole("heading", { level: 1 })).toHaveText(
      "Coaching for ages 6 and up at Riverside Shuttle Club.",
    );
    await expect(page.locator("header")).toHaveCount(1);
    await expect(page.locator("main")).toHaveCount(1);
    await expect(page.locator("footer")).toHaveCount(1);
    // The brandmark is a home link; the separate skip link targets #main.
    await expect(
      page.locator("header").getByRole("link", { name: "Riverside Shuttle Club" }),
    ).toHaveAttribute("href", "/");

    const primary = page.getByTestId("hero-primary-action");
    await expect(primary).toHaveText("Book a free trial");
    await expect(primary).toHaveAttribute("href", "#trial");
    // Brand colours come straight from the backend fields.
    await expect(primary).toHaveCSS("background-color", "rgb(15, 118, 110)");
    await expect(primary).toHaveCSS("color", "rgb(255, 255, 255)");

    await expect(page.getByRole("heading", { level: 3, name: "Shuttle Starters" })).toBeVisible();
    await expect(page.getByRole("heading", { level: 3, name: "Match Play" })).toBeVisible();
    await expect(page.getByTestId("public-class-row")).toHaveCount(4);

    const seats = page.getByTestId("public-class-seats");
    await expect(seats).toHaveText(["Open", "2 spots left", "Full, join waitlist", "Open"]);
    await expect(page.getByTestId("public-class-price").first()).toHaveText("$120 per month");

    const fullRow = page
      .getByTestId("public-class-row")
      .filter({ hasText: "Full, join waitlist" });
    await expect(fullRow.getByRole("link", { name: /^Join waitlist/ })).toBeVisible();
    await expect(fullRow.getByRole("link", { name: /^Register/ })).toHaveCount(0);

    await expect(page.getByTestId("public-coaches")).toContainText("Coach Alex Rivera");
    await expect(page.getByTestId("trial-section")).toBeVisible();
    await expect(page.getByText("214 Millbrook Road, Riverside").first()).toBeVisible();
    await expect(page.getByTestId("courtmastr-credit")).toHaveText(
      "Bookings and payments by CourtMastr",
    );
  });

  test("ships per-tenant metadata and JSON-LD without personal data", async ({ page }) => {
    await page.goto("/");
    await expect(page).toHaveTitle("Riverside Shuttle Club: classes and a free trial");
    expect(await robotsMeta(page)).not.toContain("noindex");
    await expect(page.locator('meta[property="og:image"]')).toHaveAttribute(
      "content",
      /\/og-card$/,
    );
    await expect(page.locator('link[rel="canonical"]')).toHaveAttribute("href", /\/$/);

    const blocks = await page.locator('script[type="application/ld+json"]').allTextContents();
    const graph = JSON.parse(blocks.join("")) as Array<Record<string, unknown>>;
    expect(graph[0]["@type"]).toBe("SportsActivityLocation");
    expect(graph[0].name).toBe("Riverside Shuttle Club");
    expect(JSON.stringify(graph)).not.toContain("Coach");
  });

  test("the server read forwards host and proxy secret but no credentials", async ({
    page,
    context,
    request,
    baseURL,
  }) => {
    // A signed-in visitor: the anonymous read must still carry no identity.
    await context.addCookies([
      { name: "__cm_identity", value: "e2e-secret-token", url: baseURL ?? "http://localhost" },
    ]);
    await page.goto("/");
    await expect(page.getByTestId("public-academy-page")).toBeVisible();

    const seen = (await (
      await request.get(`${STUB}/__last-request?fixture=published`)
    ).json()) as Record<string, string>;
    expect(seen["x-forwarded-host"]).toMatch(/^localhost:\d+$/);
    expect(seen["x-cm-proxy-auth"]).toBe(process.env.E2E_PROXY_SECRET);
    expect(seen.cookie).toBeUndefined();
    expect(seen.authorization).toBeUndefined();
  });

  test("serves the OG card, robots.txt and sitemap.xml for the host", async ({ request }) => {
    const headers = { "user-agent": fixtureAgent("published") };
    const og = await request.get("/og-card", { headers });
    expect(og.status()).toBe(200);
    expect(og.headers()["content-type"]).toContain("image/png");

    const robots = await request.get("/robots.txt", { headers });
    expect(robots.status()).toBe(200);
    const robotsBody = await robots.text();
    expect(robotsBody).toContain("Disallow: /admin");
    expect(robotsBody).toMatch(/Sitemap: http:\/\/localhost:\d+\/sitemap\.xml/);

    const sitemap = await request.get("/sitemap.xml", { headers });
    expect(sitemap.status()).toBe(200);
    expect(await sitemap.text()).toMatch(/<loc>http:\/\/localhost:\d+\/<\/loc>/);
  });
});

test.describe("nothing published yet", () => {
  test.use({ userAgent: fixtureAgent("empty") });

  test("shows the timetable-on-its-way notice and is not indexed", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByTestId("no-classes-published")).toContainText(
      "The new timetable is on its way",
    );
    await expect(page.getByTestId("hero-primary-action")).toHaveText("Tell me when classes open");
    await expect(page.getByTestId("public-class-row")).toHaveCount(0);
    expect(await robotsMeta(page)).toContain("noindex");
  });
});

test.describe("trials closed", () => {
  test.use({ userAgent: fixtureAgent("trials_closed") });

  test("swaps the trial actions for open classes and Register", async ({ page }) => {
    await page.goto("/");
    const primary = page.getByTestId("hero-primary-action");
    await expect(primary).toHaveText("See open classes");
    await expect(primary).toHaveAttribute("href", "#classes");
    await expect(page.getByTestId("trial-closed")).toContainText("Free trials are paused");
    await expect(page.getByRole("link", { name: /^Try a class free/ })).toHaveCount(0);
    await expect(page.getByText("First class free")).toHaveCount(0);
    await expect(page.getByRole("link", { name: /^Register for/ })).toHaveCount(3);
  });
});

test.describe("every class full", () => {
  test.use({ userAgent: fixtureAgent("all_full") });

  test("explains the waitlist and leads with it", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByTestId("all-classes-full")).toBeVisible();
    await expect(page.getByTestId("hero-primary-action")).toHaveText("Join the waitlist");
    await expect(page.getByTestId("public-class-seats")).toHaveText(
      Array(4).fill("Full, join waitlist"),
    );
  });
});

test.describe("page not published", () => {
  test.use({ userAgent: fixtureAgent("not_published") });

  test("shows branding and parent login only", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByTestId("public-page-not-published")).toBeVisible();
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("Riverside Shuttle Club");
    await expect(page.getByRole("main").getByRole("link", { name: "Parent login" })).toBeVisible();
    await expect(page.getByTestId("public-class-row")).toHaveCount(0);
    await expect(page.getByTestId("courtmastr-credit")).toBeVisible();
    expect(await robotsMeta(page)).toContain("noindex");
  });
});

test.describe("unknown host", () => {
  test.use({ userAgent: fixtureAgent("unknown") });

  test("renders the app 404", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByRole("heading", { name: "Page not found" })).toBeVisible();
    await expect(page.getByTestId("public-academy-page")).toHaveCount(0);
  });
});

test.describe("backend unavailable", () => {
  test.use({ userAgent: fixtureAgent("down") });

  test("shows a plain retry notice, never a blank page", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByTestId("public-page-unavailable")).toContainText(
      "This page is having trouble",
    );
    await expect(page.getByRole("link", { name: "Try again" })).toBeVisible();
  });
});
