/**
 * #540: the mock-api fixture must never let an unstubbed `/api/v2/**`
 * request fall through Playwright routing to the dead e2e backend
 * (127.0.0.1:8001 — nothing listens there under playwright.config.ts).
 *
 * Instead a terminal catch-all should fulfil it fast with a distinctive
 * 404 and record the path on `mock.unstubbed`, so specs can assert nothing
 * unexpected was hit.
 */

import { test, expect } from "../fixtures/mock-api";

test.describe("mock-api catch-all", () => {
  test("an unregistered /api/v2 endpoint gets a fast, well-shaped 404", async ({
    page,
    mock,
  }) => {
    await page.goto("/coach/today");
    await expect(page.getByTestId("coach-today")).toBeVisible();

    const result = await page.evaluate(async () => {
      const res = await fetch("/api/v2/does-not-exist-for-e2e");
      return { status: res.status, body: await res.json() };
    });

    expect(result.status).toBe(404);
    expect(result.body).toEqual({
      error: {
        code: "e2e_unstubbed",
        message: "/api/v2/does-not-exist-for-e2e",
      },
    });
    expect(mock.unstubbed).toContain("/api/v2/does-not-exist-for-e2e");
  });

  test("a request to a route the fixture explicitly stubs never touches the catch-all", async ({
    page,
    mock,
  }) => {
    await page.goto("/coach/today");
    await expect(page.getByTestId("coach-today")).toBeVisible();

    const result = await page.evaluate(async () => {
      const res = await fetch("/api/v2/me");
      return res.status;
    });

    expect(result).toBe(200);
    expect(mock.unstubbed).not.toContain("/api/v2/me");
  });
});
