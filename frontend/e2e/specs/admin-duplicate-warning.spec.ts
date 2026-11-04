import { expect, test, type Page, type Route } from "@playwright/test";

/**
 * People CRM Phase 4c: the duplicate warning.
 *
 * Leaving the email (or phone) field of the Add user dialog asks
 * `POST /admin/people/duplicate-check`; a match shows "Possible match:
 * <name> - open" in a polite live region, and Save still creates the user:
 * the warning never blocks. Every API is mocked; names are fake.
 */

const ACADEMY = "academy-e2e";

const ADMIN_ME = {
  user_id: "user-admin-dupes-e2e",
  email: "admin@example.com",
  academy_id: ACADEMY,
  roles: ["admin", "owner"],
};

const MATCH = {
  kind: "family",
  display_name: "Existing Testparent",
  email_masked: "ex***@example.test",
  phone_masked: "•••-2030",
  link: "/admin/families/parent-existing",
  matched_on: ["email"],
};

function fulfillJson(route: Route, body: unknown, status = 200) {
  return route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
}

interface Sent {
  checks: Array<Record<string, unknown>>;
  creates: Array<Record<string, unknown>>;
}

async function setup(page: Page): Promise<Sent> {
  const sent: Sent = { checks: [], creates: [] };
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
  await page.route("**/api/v2/admin/**", (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (request.method() === "POST" && path === "/api/v2/admin/people/duplicate-check") {
      const body = JSON.parse(request.postData() ?? "{}") as Record<string, unknown>;
      sent.checks.push(body);
      const digits = String(body.phone ?? "").replace(/\D/g, "");
      const hit = body.email === "existing@example.test" || digits === "5550102030";
      return fulfillJson(route, { matches: hit ? [MATCH] : [] });
    }
    if (request.method() === "POST" && path === "/api/v2/admin/users") {
      const body = JSON.parse(request.postData() ?? "{}") as Record<string, unknown>;
      sent.creates.push(body);
      return fulfillJson(
        route,
        {
          user_id: "user-new",
          email: body.email,
          display_name: body.display_name,
          role: body.role,
          roles: [body.role],
          status: "active",
          phone: body.phone ?? null,
          linked_student_count: 0,
          session_count: 0,
        },
        201,
      );
    }
    if (request.method() === "GET" && path === "/api/v2/admin/users") {
      return fulfillJson(route, { users: [] });
    }
    if (request.method() === "GET") return fulfillJson(route, {});
    return route.fallback();
  });
  return sent;
}

test.describe("duplicate warning on Add user (People CRM Phase 4c)", () => {
  test("a possible match is announced politely and does not block Save", async ({ page }) => {
    const sent = await setup(page);
    await page.goto("/admin/users?add=1");
    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible();

    const region = dialog.getByTestId("new-user-duplicate-region");
    await expect(region).toHaveAttribute("aria-live", "polite");
    await expect(dialog.getByTestId("new-user-duplicate")).toHaveCount(0);

    await dialog.getByTestId("new-user-name").fill("New Testparent");
    await dialog.getByTestId("new-user-email").fill("Existing@Example.test");
    await dialog.getByTestId("new-user-phone").focus(); // leaving the email field checks

    const notice = dialog.getByTestId("new-user-duplicate");
    await expect(notice).toContainText("Possible match: Existing Testparent");
    await expect(notice).toContainText("ex***@example.test");
    const open = dialog.getByTestId("new-user-duplicate-open");
    await expect(open).toHaveAttribute("href", "/admin/families/parent-existing");
    await expect(open).toHaveAttribute("target", "_blank");
    expect(sent.checks[0]).toEqual({
      email: "existing@example.test",
      phone: null,
      name: "New Testparent",
    });
    expect(JSON.stringify(sent.checks)).not.toContain("academy_id");

    // The warning never blocks: Save still creates the user.
    const save = dialog.getByRole("button", { name: "Save" });
    await expect(save).toBeEnabled();
    await save.click();
    await expect(page.getByTestId("admin-users-created")).toContainText("Added New Testparent");
    expect(sent.creates).toHaveLength(1);
    expect(sent.creates[0]).toMatchObject({ email: "existing@example.test" });
  });

  test("no match shows nothing, and a new email clears an old match", async ({ page }) => {
    const sent = await setup(page);
    await page.goto("/admin/users?add=1");
    const dialog = page.getByRole("dialog");

    await dialog.getByTestId("new-user-phone").fill("(555) 010-2030");
    await dialog.getByTestId("new-user-email").focus(); // leaving the phone field checks
    await expect(dialog.getByTestId("new-user-duplicate")).toContainText("Existing Testparent");

    await dialog.getByTestId("new-user-phone").fill("");
    await dialog.getByTestId("new-user-email").fill("brand.new@example.test");
    await dialog.getByTestId("new-user-name").focus();
    await expect
      .poll(() => sent.checks.at(-1))
      .toEqual({ email: "brand.new@example.test", phone: null, name: null });
    await expect(dialog.getByTestId("new-user-duplicate")).toHaveCount(0);
  });
});
