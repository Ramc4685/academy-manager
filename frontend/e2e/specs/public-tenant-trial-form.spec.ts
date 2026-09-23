/**
 * Lane B4: the anonymous trial request form on the public academy page.
 *
 * The page read and the form's POST (browser -> Next BFF proxy -> backend)
 * are both answered by the stub server playwright.config.ts starts
 * (e2e/fixtures/public-academy-stub.mjs); the fixture is picked by the user
 * agent, which the proxy forwards. The academy is fictional ("Riverside
 * Shuttle Club").
 */

import { expect, test, type Page } from "@playwright/test";

const STUB = `http://127.0.0.1:${process.env.PUBLIC_ACADEMY_STUB_PORT}`;

function fixtureAgent(name: string): string {
  return `Mozilla/5.0 (Playwright e2e) cm-e2e-public-fixture/${name}`;
}

async function fillValid(page: Page, name = "Jamie Testparent"): Promise<void> {
  const form = page.getByTestId("trial-request-form");
  await form.getByLabel("Your name").fill(name);
  await form.getByLabel("Email").fill("jamie.e2e@example.test");
  await form.getByLabel("Player's age").fill("9");
  await form.getByLabel("Class").selectOption({ index: 2 });
  await form.getByLabel("Riverside Shuttle Club may contact me about this request.").check();
}

test.describe("trial form, trials open", () => {
  test.use({ userAgent: fixtureAgent("published") });

  test("submits and replaces the form with a focused confirmation", async ({ page, request }) => {
    await page.goto("/");
    const form = page.getByTestId("trial-request-form");
    await expect(form).toBeVisible();
    // The honeypot is not reachable by people or assistive technology.
    await expect(page.getByRole("textbox", { name: "Leave this field empty" })).toHaveCount(0);
    await expect(form.getByTestId("trial-privacy-link")).toHaveAttribute("href", "/privacy");

    await fillValid(page);
    await form.getByTestId("trial-request-submit").click();

    const received = page.getByTestId("trial-request-received");
    await expect(received).toBeVisible();
    await expect(received).toBeFocused();
    await expect(received).toContainText("Thanks, your request is with Riverside Shuttle Club");
    await expect(received).toContainText("Nothing is booked or charged yet.");
    await expect(page.getByTestId("trial-live-region")).toHaveText(
      "Request sent to Riverside Shuttle Club.",
    );

    const sent = await (await request.get(`${STUB}/__last-trial?fixture=published`)).json();
    expect(sent).toMatchObject({
      name: "Jamie Testparent",
      email: "jamie.e2e@example.test",
      player_age: "9",
      contact_about_request: true,
      marketing_opt_in: false,
      website: "",
    });
    expect(typeof sent.class_id).toBe("string");
    expect(sent).not.toHaveProperty("child_name");
    expect(sent).not.toHaveProperty("academy_id");
  });

  test("shows an error summary that takes focus and links to each field", async ({ page }) => {
    await page.goto("/");
    const form = page.getByTestId("trial-request-form");
    await form.getByTestId("trial-request-submit").click();

    const summary = page.getByTestId("trial-error-summary");
    await expect(summary).toBeVisible();
    await expect(summary).toBeFocused();
    await expect(summary.getByRole("link")).toHaveCount(4);

    const name = form.getByLabel("Your name");
    await expect(name).toHaveAttribute("aria-invalid", "true");
    const describedBy = await name.getAttribute("aria-describedby");
    expect(describedBy).toBeTruthy();
    await expect(page.locator(`[id="${describedBy}"]`)).toHaveText("Error: Enter your name.");

    await summary.getByRole("link", { name: /^Email:/ }).click();
    await expect(form.getByLabel("Email")).toBeFocused();

    // Fixing the fields and resubmitting succeeds.
    await fillValid(page);
    await form.getByTestId("trial-request-submit").click();
    await expect(page.getByTestId("trial-request-received")).toBeVisible();
  });

  test("a trials-closed answer while the page is open shows the closed notice", async ({
    page,
  }) => {
    await page.goto("/");
    await fillValid(page, "Closed Race");
    await page.getByTestId("trial-request-submit").click();
    const closed = page.getByTestId("trial-request-closed");
    await expect(closed).toBeVisible();
    await expect(closed).toContainText("Free trials are paused");
    await expect(page.getByTestId("trial-request-form")).toHaveCount(0);
  });
});

test.describe("trial form, trials closed", () => {
  test.use({ userAgent: fixtureAgent("trials_closed") });

  test("renders no form, only the trials-closed notice", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByTestId("trial-closed")).toBeVisible();
    await expect(page.getByTestId("trial-request-form")).toHaveCount(0);
  });
});
