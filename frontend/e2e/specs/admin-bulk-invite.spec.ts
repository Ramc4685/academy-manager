import { expect, test, type Page, type Route } from "@playwright/test";

/**
 * UIM6 (#449) — bulk-invite parents from the users directory.
 *
 * `POST /admin/users/bulk-invite` has existed since the directory shipped, but
 * nothing in the UI called it: onboarding a season's worth of parents meant
 * opening the single-create dialog once per family. These specs drive the paste
 * → preview → result flow against a mocked endpoint, including the two things
 * that must never reach the backend — rows that cannot succeed, and a batch
 * over the endpoint's 100-row cap.
 */

const ACADEMY = "academy-e2e";

const ADMIN_ME = {
  user_id: "user-admin-449-e2e",
  email: "admin@example.com",
  academy_id: ACADEMY,
  roles: ["admin", "owner"],
};

function fulfillJson(route: Route, body: unknown, status = 200) {
  return route.fulfill({
    status,
    contentType: "application/json",
    body: JSON.stringify(body),
  });
}

async function stubAdminShell(page: Page) {
  await page.route("**/api/v2/me", (route) => {
    if (route.request().method() !== "GET") return route.fallback();
    return fulfillJson(route, ADMIN_ME);
  });
  await page.route("**/api/v2/me/memberships", (route) => {
    if (route.request().method() !== "GET") return route.fallback();
    return fulfillJson(route, {
      memberships: [
        {
          academy_id: ACADEMY,
          academy_name: "Academy E2E",
          academy_slug: ACADEMY,
          roles: ["admin", "owner"],
          status: "active",
          is_default: true,
        },
      ],
      active_academy_id: ACADEMY,
    });
  });
  await page.route("**/api/v2/admin/messages*", (route) =>
    fulfillJson(route, { messages: [], unread_count: 0 }),
  );
}

const BULK_RESPONSE = {
  created: 1,
  skipped: 1,
  failed: 1,
  results: [
    { email: "ana@example.com", status: "created", user_id: "user-ana", detail: null },
    {
      email: "bo@example.com",
      status: "skipped",
      user_id: null,
      detail: "email already exists",
    },
    {
      email: "cy@example.com",
      status: "failed",
      user_id: null,
      detail: "user creation failed",
    },
  ],
};

/** Payloads the page actually POSTed, so a spec can assert what was sent. */
type Sent = Array<{ users: Array<{ email: string; display_name: string }>; reason?: string }>;

async function stubDirectory(page: Page, sent: Sent) {
  await page.route("**/api/v2/admin/**", (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;

    if (request.method() === "POST" && path === "/api/v2/admin/users/bulk-invite") {
      sent.push(JSON.parse(request.postData() ?? "{}"));
      return fulfillJson(route, BULK_RESPONSE);
    }
    if (request.method() === "GET" && path === "/api/v2/admin/users") {
      return fulfillJson(route, { users: [] });
    }
    if (request.method() === "GET") return fulfillJson(route, {});
    return route.fallback();
  });
}

test.describe("admin bulk invite parents (#449)", () => {
  let sent: Sent;

  test.beforeEach(async ({ page }) => {
    sent = [];
    await stubAdminShell(page);
    await stubDirectory(page, sent);
    await page.goto("/admin/users?role=parent");
    await expect(page.getByTestId("admin-users")).toBeVisible();
  });

  test("the directory offers a bulk invite action that opens the dialog", async ({ page }) => {
    const trigger = page.getByTestId("admin-users-bulk-invite");
    await expect(trigger).toBeVisible();
    await trigger.click();

    await expect(page.getByTestId("bulk-invite-dialog")).toBeVisible();
    await expect(page.getByRole("dialog")).toContainText("Bulk invite parents");
    // Nothing pasted yet: there is nothing to send.
    await expect(page.getByTestId("bulk-invite-submit")).toBeDisabled();
  });

  test("pasted rows are previewed, deduped and validated before submit", async ({ page }) => {
    await page.getByTestId("admin-users-bulk-invite").click();
    await page.getByTestId("bulk-invite-textarea").fill(
      [
        "ana@example.com, Ana Parent",
        "bo@example.com, Bo Parent",
        "ANA@example.com, Ana Again",
        "not-an-email, Broken Row",
      ].join("\n"),
    );

    await expect(page.getByTestId("bulk-invite-preview-count")).toContainText("2 to invite");
    await expect(page.getByTestId("bulk-invite-preview-count")).toContainText("1 duplicate");
    await expect(page.getByTestId("bulk-invite-preview-count")).toContainText("1 invalid");
    await expect(page.getByTestId("bulk-invite-submit")).toHaveText("Send 2 invites");
  });

  test("a batch over the 100-row cap is blocked client-side", async ({ page }) => {
    const rows = Array.from(
      { length: 101 },
      (_, i) => `parent${i}@example.com, Parent ${i}`,
    ).join("\n");

    await page.getByTestId("admin-users-bulk-invite").click();
    await page.getByTestId("bulk-invite-textarea").fill(rows);

    await expect(page.getByTestId("bulk-invite-limit-error")).toBeVisible();
    await expect(page.getByTestId("bulk-invite-submit")).toBeDisabled();
    expect(sent).toHaveLength(0);
  });

  test("submitting posts only the valid rows and renders created/skipped/failed", async ({
    page,
  }) => {
    await page.getByTestId("admin-users-bulk-invite").click();
    await page.getByTestId("bulk-invite-textarea").fill(
      [
        "ana@example.com, Ana Parent",
        "bo@example.com, Bo Parent",
        "cy@example.com, Cy Parent",
        "nope, Broken Row",
      ].join("\n"),
    );
    await page.getByTestId("bulk-invite-submit").click();

    const results = page.getByTestId("bulk-invite-results");
    await expect(results).toBeVisible();
    await expect(page.getByTestId("bulk-invite-result-summary")).toHaveText(
      "1 created · 1 skipped · 1 failed",
    );
    await expect(page.getByTestId("bulk-invite-result-row-ana@example.com")).toContainText(
      "CREATED",
    );
    await expect(page.getByTestId("bulk-invite-result-row-bo@example.com")).toContainText(
      "email already exists",
    );
    await expect(page.getByTestId("bulk-invite-result-row-cy@example.com")).toContainText("FAILED");

    // The malformed row never left the browser.
    expect(sent).toHaveLength(1);
    expect(sent[0].users).toEqual([
      { email: "ana@example.com", display_name: "Ana Parent" },
      { email: "bo@example.com", display_name: "Bo Parent" },
      { email: "cy@example.com", display_name: "Cy Parent" },
    ]);
  });

  test("retry failed re-seeds the input with only the failed rows", async ({ page }) => {
    await page.getByTestId("admin-users-bulk-invite").click();
    await page
      .getByTestId("bulk-invite-textarea")
      .fill(["ana@example.com, Ana Parent", "cy@example.com, Cy Parent"].join("\n"));
    await page.getByTestId("bulk-invite-submit").click();

    await page.getByTestId("bulk-invite-retry-failed").click();

    await expect(page.getByTestId("bulk-invite-textarea")).toHaveValue(
      "cy@example.com, Cy Parent",
    );
    await expect(page.getByTestId("bulk-invite-submit")).toHaveText("Send 1 invite");
  });
});
