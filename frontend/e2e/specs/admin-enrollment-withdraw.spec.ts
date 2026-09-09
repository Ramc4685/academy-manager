import { expect, test, type Page, type Route } from "@playwright/test";

/**
 * Issue #670: one withdraw path. The session-detail Drop dialog (opened from
 * the roster row's overflow menu, #696) sends every outcome — including the
 * account credit an owner used to approve through a separate route — to
 * `POST /admin/enrollments/{id}/withdraw`, and surfaces the 409 the backend
 * returns when the row already moved on.
 */

const ACADEMY = "academy-e2e";
const SESSION_ID = "sess-withdraw";
const ENROLLMENT_ID = "enr-withdraw-1";

function adminMe(roles: string[]) {
  return {
    user_id: "user-admin-withdraw-e2e",
    email: "admin@example.com",
    academy_id: ACADEMY,
    roles,
  };
}

function fulfillJson(route: Route, body: unknown, status = 200) {
  return route.fulfill({
    status,
    contentType: "application/json",
    body: JSON.stringify(body),
  });
}

async function stubAdminShell(page: Page, roles: string[]) {
  await page.route("**/api/v2/me", (route) => {
    if (route.request().method() !== "GET") return route.fallback();
    return fulfillJson(route, adminMe(roles));
  });
  await page.route("**/api/v2/me/memberships", (route) => {
    if (route.request().method() !== "GET") return route.fallback();
    return fulfillJson(route, {
      memberships: [
        {
          academy_id: ACADEMY,
          academy_name: "Academy E2E",
          academy_slug: ACADEMY,
          roles,
          status: "active",
          is_default: true,
        },
      ],
      active_academy_id: ACADEMY,
    });
  });
  // Both shells poll the message inbox on every page; keep it quiet.
  await page.route("**/api/v2/admin/messages*", (route) =>
    fulfillJson(route, { messages: [], unread_count: 0 }),
  );
}

interface WithdrawStub {
  /** Bodies posted to the withdraw route, in order. */
  withdrawBodies: unknown[];
  /** Any call to the removed owner-only approve route is a regression. */
  approveCalls: number;
  /** What the withdraw route answers; tests switch it mid-flight. */
  respond: (route: Route) => Promise<void>;
}

async function stubSessionDetail(page: Page, enrollmentStatus = "active"): Promise<WithdrawStub> {
  const stub: WithdrawStub = {
    withdrawBodies: [],
    approveCalls: 0,
    respond: (route) => route.fulfill({ status: 204, body: "" }),
  };
  await page.route("**/api/v2/admin/**", (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    if (request.method() === "GET" && path === `/api/v2/admin/sessions/${SESSION_ID}`) {
      return fulfillJson(route, {
        session_id: SESSION_ID,
        coach_id: "coach-1",
        coach_name: "Coach One",
        title: "Tuesday 6:00 PM - 6:45 PM Beginner",
        location: "Court 1",
        start_at: "2026-09-08T23:00:00Z",
        end_at: "2026-09-08T23:45:00Z",
        days_of_week: ["Tue"],
        start_time: "18:00",
        end_time: "18:45",
        timezone: "America/Chicago",
        capacity: 12,
        status: "scheduled",
        enrolled_count: 1,
        waitlist_count: 0,
      });
    }
    if (request.method() === "GET" && path === `/api/v2/admin/sessions/${SESSION_ID}/enrollments`) {
      return fulfillJson(route, {
        enrollments: [
          {
            enrollment_id: ENROLLMENT_ID,
            session_id: SESSION_ID,
            student_id: "stu-1",
            parent_id: "parent-1",
            full_name: "Alice Example",
            status: enrollmentStatus,
            enrolled_at: "2026-08-01T00:00:00Z",
          },
        ],
      });
    }
    if (request.method() === "GET" && path === `/api/v2/admin/sessions/${SESSION_ID}/occurrences`) {
      return fulfillJson(route, { occurrences: [] });
    }
    if (request.method() === "GET" && path === `/api/v2/admin/sessions/${SESSION_ID}/waitlist`) {
      return fulfillJson(route, { waitlist: [] });
    }
    if (request.method() === "GET" && path === "/api/v2/admin/users") {
      return fulfillJson(route, { users: [] });
    }
    if (
      request.method() === "POST" &&
      path === `/api/v2/admin/enrollments/${ENROLLMENT_ID}/withdrawal-credit/preview`
    ) {
      return fulfillJson(route, {
        credit_amount_cents: 3750,
        display_amount: "$37.50",
        total_classes: 8,
        unused_classes: 3,
        formula: "max(10000 - 0, 0) * 3 / 8",
        message: "Credit is calculated for 3 unused classes.",
        no_credit_reason: null,
      });
    }
    if (request.method() === "POST" && path.endsWith("/withdrawal-credit/approve")) {
      stub.approveCalls += 1;
      return fulfillJson(route, { detail: "Not found" }, 404);
    }
    if (request.method() === "POST" && path === `/api/v2/admin/enrollments/${ENROLLMENT_ID}/withdraw`) {
      stub.withdrawBodies.push(request.postDataJSON());
      return stub.respond(route);
    }
    if (request.method() === "GET") return fulfillJson(route, {});
    return route.fallback();
  });
  return stub;
}

async function openWithdrawDialog(page: Page) {
  await page.goto(`/admin/sessions/${SESSION_ID}`);
  await expect(page.getByText("Alice Example")).toBeVisible();
  await page.getByRole("button", { name: "More actions for Alice Example" }).click();
  await page.getByRole("menuitem", { name: "Drop" }).click();
  await expect(page.getByRole("dialog", { name: "Drop enrollment" })).toBeVisible();
}

test.describe("admin enrollment withdraw dialog (#670)", () => {
  test("owner: account credit goes through the single withdraw route", async ({ page }) => {
    await stubAdminShell(page, ["admin", "owner"]);
    const stub = await stubSessionDetail(page);
    await openWithdrawDialog(page);

    const dialog = page.getByRole("dialog", { name: "Drop enrollment" });
    await expect(dialog.getByLabel("Outcome")).toHaveValue("credit");
    await dialog.getByLabel("Drop date").fill("2026-09-15");
    await dialog.getByRole("button", { name: "Preview credit" }).click();
    await expect(dialog.getByText("Credit: $37.50")).toBeVisible();
    await dialog.getByLabel("Admin note").fill("Moving away");
    await dialog.getByRole("button", { name: "Drop", exact: true }).click();

    await expect(dialog).toBeHidden();
    expect(stub.approveCalls).toBe(0);
    expect(stub.withdrawBodies).toEqual([
      { effective_date: "2026-09-15", outcome: "credit", reason: "Moving away" },
    ]);
  });

  test("admin without owner: credit is disabled, refund goes through the same route", async ({
    page,
  }) => {
    await stubAdminShell(page, ["admin"]);
    const stub = await stubSessionDetail(page);
    await openWithdrawDialog(page);

    const dialog = page.getByRole("dialog", { name: "Drop enrollment" });
    await expect(dialog.getByLabel("Outcome")).toHaveValue("refund");
    // toBeDisabled() does not treat <option> as a form control; check the attribute.
    await expect(dialog.getByLabel("Outcome").locator("option[value='credit']")).toHaveAttribute("disabled", "");
    await expect(dialog.getByText("Only the academy owner can issue an account credit.")).toBeVisible();
    await expect(dialog.getByRole("button", { name: "Preview credit" })).toHaveCount(0);
    await dialog.getByLabel("Drop date").fill("2026-09-15");
    await dialog.getByRole("button", { name: "Drop", exact: true }).click();

    await expect(dialog).toBeHidden();
    expect(stub.approveCalls).toBe(0);
    expect(stub.withdrawBodies).toEqual([
      { effective_date: "2026-09-15", outcome: "refund", reason: "Withdrawal refund" },
    ]);
  });

  test("a row that already moved on surfaces the backend's 409 message", async ({ page }) => {
    await stubAdminShell(page, ["admin", "owner"]);
    const stub = await stubSessionDetail(page);
    stub.respond = (route) =>
      fulfillJson(
        route,
        {
          error: {
            code: "Enrollment.NotWithdrawable",
            message: "Enrollment is already withdrawn; it cannot be withdrawn again.",
            details: { enrollment_id: ENROLLMENT_ID, status: "withdrawn" },
          },
        },
        409,
      );
    await openWithdrawDialog(page);

    const dialog = page.getByRole("dialog", { name: "Drop enrollment" });
    await dialog.getByLabel("Outcome").selectOption("adjustment");
    await dialog.getByLabel("Drop date").fill("2026-09-15");
    await dialog.getByRole("button", { name: "Drop", exact: true }).click();

    await expect(dialog.getByRole("alert")).toHaveText(
      "Enrollment is already withdrawn; it cannot be withdrawn again.",
    );
    await expect(dialog).toBeVisible();
    expect(stub.withdrawBodies).toHaveLength(1);
  });

  test("a 404 with a domain code is not reported as a permissions problem", async ({ page }) => {
    // The owner IS the owner; telling them to ask the academy owner hid the
    // real cause (issue #670 review). The copy is keyed off the error code.
    await stubAdminShell(page, ["admin", "owner"]);
    const stub = await stubSessionDetail(page);
    stub.respond = (route) =>
      fulfillJson(
        route,
        {
          error: {
            code: "Billing.PaymentNotFound",
            message: "paid payment snapshot not found",
            details: { enrollment_id: ENROLLMENT_ID },
          },
        },
        404,
      );
    await openWithdrawDialog(page);

    const dialog = page.getByRole("dialog", { name: "Drop enrollment" });
    // The copy is keyed off the error code, not the outcome, so this drives it
    // through an outcome that needs no credit preview to enable Withdraw.
    await dialog.getByLabel("Outcome").selectOption("adjustment");
    await dialog.getByLabel("Drop date").fill("2026-09-15");
    await dialog.getByRole("button", { name: "Drop", exact: true }).click();

    const alert = dialog.getByRole("alert");
    await expect(alert).toContainText("no paid tuition");
    await expect(alert).not.toContainText("permission");
  });
});
