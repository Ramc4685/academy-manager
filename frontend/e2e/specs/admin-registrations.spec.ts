import { expect, test, type Page, type Route } from "@playwright/test";

const ADMIN_ME = {
  user_id: "admin-registration-e2e",
  email: "admin@example.com",
  academy_id: "academy-e2e",
  roles: ["admin"],
};

const PENDING = {
  application_id: "app-1",
  status: "PENDING_APPROVAL",
  parent_email: "parent@example.com",
  parent_name: "Pat Parent",
  student_name: "Sam Student",
  selected_session_id: "session-1",
  waiver_required: true,
  waiver_satisfied: true,
  updated_at: "2026-07-14T12:00:00Z",
  parent_user_id: "parent-1",
  child_first_name: "Sam",
  child_last_name: "Student",
  child_skill_level: "beginner",
  payment_id: null,
  student_id: null,
  enrollment_id: null,
  waitlist_id: null,
  session_title: "Wednesday Beginner",
  session_capacity: 16,
  waiver_template_id: "waiver-1",
  waiver_title: "Liability Waiver",
  waiver_version: "1.0",
};

function fulfillJson(route: Route, body: unknown, status = 200) {
  return route.fulfill({
    status,
    contentType: "application/json",
    body: JSON.stringify(body),
  });
}

async function stubAdminShell(page: Page) {
  await page.route("**/api/v2/me", (route) => fulfillJson(route, ADMIN_ME));
  await page.route("**/api/v2/me/memberships", (route) =>
    fulfillJson(route, {
      memberships: [
        {
          academy_id: "academy-e2e",
          academy_name: "Rally Academy",
          academy_slug: "academy-e2e",
          roles: ["admin"],
          status: "active",
          is_default: true,
        },
      ],
      active_academy_id: "academy-e2e",
    }),
  );
  await page.route("**/api/v2/admin/academy", (route) =>
    fulfillJson(route, {
      academy_id: "academy-e2e",
      display_name: "Rally Academy",
      timezone: "America/Chicago",
      contact_email: null,
      contact_phone: null,
      hours_text: null,
      address: null,
      logo_url: null,
      brand_color: null,
    }),
  );
}

test("successful approval stays successful without a redundant detail refetch", async ({ page }) => {
  await stubAdminShell(page);
  let detailGets = 0;
  await page.route("**/api/v2/admin/registrations/app-1", (route) => {
    if (route.request().method() !== "GET") return route.fallback();
    detailGets += 1;
    if (detailGets > 1) {
      return fulfillJson(route, { detail: "temporary read failure" }, 500);
    }
    return fulfillJson(route, PENDING);
  });
  await page.route("**/api/v2/admin/registrations/app-1/approve", (route) =>
    fulfillJson(route, {
      ...PENDING,
      status: "APPROVED",
      student_id: "student-1",
      enrollment_id: "enrollment-1",
      updated_at: "2026-07-14T12:01:00Z",
    }),
  );
  await page.route("**/api/v2/admin/registrations", (route) =>
    fulfillJson(route, { registrations: [] }),
  );

  await page.goto("/admin/registrations/app-1");
  await expect(page.getByTestId("admin-registration-detail")).toBeVisible();
  await page.getByRole("button", { name: "Approve", exact: true }).click();

  await expect(page.getByText("APPROVED")).toBeVisible();
  await expect(page.getByText("Could not load registration.")).toHaveCount(0);
  expect(detailGets).toBe(1);
});

test("ambiguous child registration stays visible with manual-review guidance", async ({ page }) => {
  await stubAdminShell(page);
  await page.route("**/api/v2/admin/registrations/app-1", (route) =>
    fulfillJson(route, { ...PENDING, status: "MANUAL_REVIEW" }),
  );

  await page.goto("/admin/registrations/app-1");

  await expect(page.getByText(/matches more than one legacy record/)).toBeVisible();
  await expect(page.getByRole("button", { name: "Approve", exact: true })).toBeDisabled();
  await expect(page.getByRole("button", { name: "Waitlist", exact: true })).toBeDisabled();
  await expect(page.getByRole("button", { name: "Reject", exact: true })).toBeDisabled();
});

test("stale approval recovery exposes only the original decision", async ({ page }) => {
  await stubAdminShell(page);
  await page.route("**/api/v2/admin/registrations/app-1", (route) =>
    fulfillJson(route, { ...PENDING, status: "APPROVING" }),
  );

  await page.goto("/admin/registrations/app-1");

  await expect(page.getByRole("button", { name: "Approve", exact: true })).toBeEnabled();
  await expect(page.getByRole("button", { name: "Waitlist", exact: true })).toBeDisabled();
  await expect(page.getByRole("button", { name: "Reject", exact: true })).toBeDisabled();
});
