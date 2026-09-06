import { expect, test, type Page, type Route } from "@playwright/test";

const ADMIN_ME = {
  user_id: "user-admin-students-e2e",
  email: "admin@example.com",
  academy_id: "academy-e2e",
  roles: ["admin"],
};

const BENIGN_PATTERNS: RegExp[] = [
  /Download the React DevTools/i,
  /Fast Refresh/i,
  /HMR/i,
  /webpack-internal/i,
];

function isBenign(message: string): boolean {
  return BENIGN_PATTERNS.some((re) => re.test(message));
}

function collectConsoleErrors(page: Page): string[] {
  const errors: string[] = [];
  page.on("console", (msg) => {
    if (msg.type() === "error" && !isBenign(msg.text())) {
      errors.push(msg.text());
    }
  });
  return errors;
}

function fulfillJson(route: Route, body: unknown, status = 200) {
  return route.fulfill({
    status,
    contentType: "application/json",
    body: JSON.stringify(body),
  });
}

async function stubMe(page: Page) {
  await page.route("**/api/v2/me", (route) => {
    if (route.request().method() !== "GET") return route.fallback();
    return fulfillJson(route, ADMIN_ME);
  });
  await page.route("**/api/v2/me/memberships", (route) => {
    if (route.request().method() !== "GET") return route.fallback();
    return fulfillJson(route, {
      memberships: [
        {
          academy_id: "academy-e2e",
          academy_name: "Academy E2E",
          academy_slug: "academy-e2e",
          roles: ["admin"],
          status: "active",
          is_default: true,
        },
      ],
      active_academy_id: "academy-e2e",
    });
  });
}

async function stubAdminAcademy(page: Page) {
  await page.route(/\/api\/v2\/admin\/academy(?:\?.*)?$/, (route) => {
    if (route.request().method() !== "GET") return route.fallback();
    return fulfillJson(route, {
      academy_id: "academy-e2e",
      display_name: "Academy E2E",
      timezone: "UTC",
      contact_email: null,
      contact_phone: null,
      hours_text: null,
      address: null,
    });
  });
}

test.describe("admin students", () => {
  test("searches, filters, and loads the next cursor using BFF-rendered attendance and dues", async ({
    page,
  }) => {
    const errors = collectConsoleErrors(page);
    const requests: string[] = [];
    await stubMe(page);
    await stubAdminAcademy(page);
    await page.route("**/api/v2/admin/students*", (route) => {
      if (route.request().method() !== "GET") return route.fallback();
      const url = new URL(route.request().url());
      requests.push(url.search);
      const search = url.searchParams.get("search") ?? "";
      const status = url.searchParams.get("status") ?? "";
      const cursor = url.searchParams.get("cursor") ?? "";

      if (status === "paused") {
        return fulfillJson(route, {
          students: [
            {
              student_id: "student-paused",
              full_name: "Maya Paused",
              parent_id: "parent-paused",
              parent_name: "Rina Paused",
              parent_email: "rina@example.com",
              status: "paused",
              active_session_count: 0,
              last_seen_at: null,
              attendance_rate: null,
              dues_status: "overdue",
            },
          ],
          next_cursor: null,
        });
      }

      if (search === "zara") {
        return fulfillJson(route, {
          students: [
            {
              student_id: "student-zara",
              full_name: "Zara Khan",
              parent_id: "parent-zara",
              parent_name: "Aakash Khan",
              parent_email: "aakash@example.com",
              status: "active",
              active_session_count: 1,
              last_seen_at: "2026-05-12T15:00:00Z",
              attendance_rate: 0.72,
              dues_status: "due",
            },
          ],
          next_cursor: null,
        });
      }

      if (cursor === "cursor-2") {
        return fulfillJson(route, {
          students: [
            {
              student_id: "student-3",
              full_name: "Priya Shah",
              parent_id: "parent-3",
              parent_name: "Nisha Shah",
              parent_email: "nisha@example.com",
              status: "inactive",
              active_session_count: 0,
              last_seen_at: null,
              attendance_rate: null,
              dues_status: "overdue",
            },
          ],
          next_cursor: null,
        });
      }

      return fulfillJson(route, {
        students: [
          {
            student_id: "student-1",
            full_name: "Amit Rao",
            parent_id: "parent-1",
            parent_name: "Rohan Rao",
            parent_email: "rohan@example.com",
            status: "active",
            active_session_count: 2,
            last_seen_at: "2026-05-18T15:00:00Z",
            attendance_rate: 0.91,
            dues_status: "current",
          },
          {
            student_id: "student-2",
            full_name: "Leah Chen",
            parent_id: "parent-2",
            parent_name: "Min Chen",
            parent_email: "min@example.com",
            status: "active",
            active_session_count: 1,
            last_seen_at: "2026-05-17T15:00:00Z",
            attendance_rate: 0.5,
            dues_status: "due",
          },
        ],
        next_cursor: "cursor-2",
      });
    });

    await page.goto("/admin/students");
    await expect(page.getByTestId("admin-students-row-student-1")).toContainText("Amit Rao");
    await expect(page.getByTestId("admin-students-row-student-1")).toContainText("91%");
    await expect(page.getByTestId("admin-students-row-student-1")).toContainText("CURRENT");
    await expect(requests[0]).toContain("limit=25");

    await page.getByRole("button", { name: /^next page$/i }).click();
    await expect(page.getByTestId("admin-students-row-student-3")).toContainText("Priya Shah");
    expect(requests.some((search) => search.includes("cursor=cursor-2"))).toBe(true);

    await page.getByLabel("Search students").fill("zara");
    await expect(page.getByTestId("admin-students-row-student-zara")).toContainText("Zara Khan");
    await expect(page.getByTestId("admin-students-row-student-zara")).toContainText("72%");
    await expect(page.getByTestId("admin-students-row-student-1")).toHaveCount(0);
    expect(requests.at(-1)).toContain("search=zara");
    expect(requests.at(-1)).not.toContain("cursor=");

    await page.getByRole("button", { name: /^paused/i }).click();
    await expect(page.getByTestId("admin-students-row-student-paused")).toContainText("Maya Paused");
    expect(requests.at(-1)).toContain("status=paused");
    expect(requests.at(-1)).not.toContain("cursor=");
    expect(errors, `App console errors: ${errors.join("\n")}`).toEqual([]);
  });

  test("shows a truthful empty state", async ({ page }) => {
    await stubMe(page);
    await stubAdminAcademy(page);
    await page.route("**/api/v2/admin/students*", (route) => {
      if (route.request().method() !== "GET") return route.fallback();
      return fulfillJson(route, { students: [], next_cursor: null });
    });

    await page.goto("/admin/students");
    await expect(page.getByTestId("admin-students-empty")).toContainText("No students registered yet.");
  });

  test("shows a truthful error state", async ({ page }) => {
    await stubMe(page);
    await stubAdminAcademy(page);
    await page.route("**/api/v2/admin/students*", (route) => {
      if (route.request().method() !== "GET") return route.fallback();
      return fulfillJson(route, { error: { message: "boom" } }, 500);
    });

    await page.goto("/admin/students");
    await expect(page.getByTestId("admin-students-error")).toContainText("Could not load students.");
  });

  test("renders the student profile with enrolled sessions and payment history", async ({
    page,
  }) => {
    const errors = collectConsoleErrors(page);
    let patchBody: unknown = null;
    const studentFixture = {
      student_id: "student-1",
      full_name: "Amit Rao",
      parent_id: "parent-1",
      parent_name: "Rohan Rao",
      parent_email: "rohan@example.com",
      parent_phone: "555-0101",
      status: "active",
      active_session_count: 1,
      last_seen_at: "2026-05-18T15:00:00Z",
      attendance_rate: 0.91,
      dues_status: "due",
      date_of_birth: "2015-04-10",
      level: "intermediate",
      notes: "Prefers evening sessions",
      parent_details: null,
      previous_experience: "Two years of club play",
      medical_notes: "Peanut allergy",
      emergency_contact_name: "Anita Chen",
      emergency_contact_phone: "555-0199",
      t_shirt_size: "M",
      waiver_status: "signed",
      waiver_signed_at: "2026-05-10T15:00:00Z",
      waiver_version: "2026-v1",
      recent_attendance: [
        {
          session_id: "sess-1",
          date: "2026-05-18",
          status: "present",
          marked_at: "2026-05-18T15:00:00Z",
        },
        {
          session_id: "sess-1",
          date: "2026-05-11",
          status: "absent",
          marked_at: "2026-05-11T15:00:00Z",
        },
      ],
      enrolled_sessions: [
        {
          enrollment_id: "enr-1",
          session_id: "sess-1",
          session_title: "Advanced Footwork",
          location: "Court 1",
          start_at: "2026-06-02T21:00:00Z",
          end_at: "2026-06-02T22:00:00Z",
          status: "active",
          payment_mode: "monthly",
          subscription_status: "active",
          amount_cents: 15000,
        },
      ],
      payment_history: [
        {
          payment_id: "pay-1",
          session_id: "sess-1",
          period: "2026-06",
          amount_cents: 15000,
          paid_amount_cents: 4000,
          balance_due_cents: 11000,
          status: "partially_paid",
          payment_method: "cash",
          created_at: "2026-06-01T15:00:00Z",
        },
      ],
      current_payment: {
        amount_cents: 11000,
        source: "invoice",
        status: "partially_paid",
        period: "2026-06",
        payment_id: "pay-1",
        session_id: "sess-1",
      },
    };
    await stubMe(page);
    await stubAdminAcademy(page);
    await page.route("**/api/v2/admin/users?role=parent", (route) => {
      if (route.request().method() !== "GET") return route.fallback();
      return fulfillJson(route, {
        users: [
          {
            user_id: "parent-1",
            email: "rohan@example.com",
            display_name: "Rohan Rao",
            role: "parent",
            status: "active",
            phone: "555-0101",
          },
        ],
      });
    });
    await page.route("**/api/v2/admin/programs*", (route) => {
      if (route.request().method() !== "GET") return route.fallback();
      return fulfillJson(route, { programs: [] });
    });
    // The Billing tab's session-type panel reads these; without mocks they 401
    // and trip this spec's "no console errors" assertion.
    await page.route("**/api/v2/admin/billing-enrollments*", (route) => {
      if (route.request().method() !== "GET") return route.fallback();
      return fulfillJson(route, { enrollments: [] });
    });
    await page.route("**/api/v2/admin/session-types*", (route) => {
      if (route.request().method() !== "GET") return route.fallback();
      return fulfillJson(route, { session_types: [] });
    });
    await page.route("**/api/v2/admin/students/student-1", (route) => {
      if (route.request().method() === "PATCH") {
        const requestBody = route.request().postDataJSON() as Record<string, unknown>;
        patchBody = requestBody;
        return fulfillJson(route, {
          ...studentFixture,
          medical_notes: requestBody.medical_notes,
        });
      }
      if (route.request().method() !== "GET") return route.fallback();
      return fulfillJson(route, studentFixture);
    });

    await page.goto("/admin/students/student-1");
    await page.waitForLoadState("networkidle");
    await expect(page.getByTestId("admin-student-detail")).toContainText("Amit Rao");
    await expect(page.getByTestId("admin-student-summary-strip")).toContainText("$110");
    await expect(page.getByTestId("admin-student-summary-strip")).toContainText("91%");
    await expect(page.getByRole("tab", { name: "Training" })).toBeVisible();

    await page.getByRole("tab", { name: "Training" }).click();
    await expect(page.getByTestId("admin-student-training-tab")).toContainText(
      "Two years of club play",
    );
    await expect(page.getByLabel("Previous experience")).toHaveAttribute(
      "maxlength",
      "1000",
    );
    await expect(page.getByLabel("Medical notes")).toHaveValue("Peanut allergy");
    await expect(page.getByLabel("Medical notes")).toHaveAttribute("maxlength", "1000");
    await expect(page.getByLabel("Emergency contact name")).toHaveValue("Anita Chen");
    await expect(page.getByLabel("Emergency contact phone")).toHaveValue("555-0199");
    await expect(page.getByLabel("Emergency contact phone")).toHaveAttribute(
      "maxlength",
      "40",
    );
    await expect(page.getByTestId("admin-student-recent-attendance")).toContainText(
      "PRESENT",
    );
    const trainingForm = page.getByTestId("admin-student-training-edit-form");
    const medicalNotes = trainingForm.getByLabel("Medical notes");
    await medicalNotes.focus();
    await page.keyboard.press(process.platform === "darwin" ? "Meta+A" : "Control+A");
    await page.keyboard.press("Backspace");
    await expect(medicalNotes).toHaveValue("");
    await trainingForm.getByRole("button", { name: /^save changes$/i }).click();
    expect(patchBody).toMatchObject({
      medical_notes: "",
      reason: "Admin profile update",
    });

    await page.getByRole("tab", { name: "Sessions" }).click();
    await expect(page.getByTestId("admin-student-enrolled-sessions")).toContainText(
      "Advanced Footwork",
    );
    await expect(page.getByTestId("admin-student-enrolled-sessions")).toContainText("$150");

    await page.getByRole("tab", { name: "Billing" }).click();
    await expect(page.getByTestId("admin-student-family-billing-link")).toContainText(
      "Open family billing",
    );
    await expect(
      page.getByTestId("admin-student-family-billing-link").getByRole("link"),
    ).toHaveAttribute("href", /\/admin\/families\//);

    await page.getByRole("tab", { name: "Family & Compliance" }).click();
    await expect(page.getByTestId("admin-student-compliance-tab")).toContainText("2026-v1");
    await expect(page.getByLabel("T-shirt size")).toHaveValue("M");
    await expect(page.getByLabel("T-shirt size")).toHaveAttribute("maxlength", "20");
    expect(errors, `App console errors: ${errors.join("\n")}`).toEqual([]);
  });
});
