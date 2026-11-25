/**
 * Coach release cut: Today's empty state points at the next class and the
 * recap left open; inside a class the coach steps attendance → skills → recap;
 * the class screen says whether marks are Saved, Waiting to sync, or Need
 * attention, and a queued mark survives a reload and syncs once.
 */

import type { Page, Route } from "@playwright/test";

import { test, expect } from "../fixtures/mock-api";

function localISO(offsetDays = 0): string {
  const d = new Date();
  d.setDate(d.getDate() + offsetDays);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(
    d.getDate(),
  ).padStart(2, "0")}`;
}

const HOUR = 60 * 60 * 1000;

async function stubPastAndNextClass(page: Page) {
  const yesterdayStart = new Date(Date.now() - 20 * HOUR).toISOString();
  const nextStart = new Date(Date.now() + 30 * HOUR).toISOString();
  await page.route("**/api/v2/coach/today*", async (route: Route) => {
    if (route.request().method() !== "GET") return route.fallback();
    const date = new URL(route.request().url()).searchParams.get("date");
    const sessions =
      date === localISO(-1) || date === localISO(-2)
        ? [
            {
              session_id: "s-past",
              occurrence_id: "occ-past",
              title: "Junior B",
              location: "Court 2",
              start_at: yesterdayStart,
              end_at: new Date(Date.parse(yesterdayStart) + HOUR).toISOString(),
              roster: [
                {
                  student_id: "st9",
                  full_name: "Casey Test",
                  enrollment_status: "active",
                  attendance_status: "present",
                },
              ],
              recap_saved: false,
            },
          ]
        : [];
    return route.fulfill({ json: { date, sessions } });
  });
  await page.route("**/api/v2/coach/sessions", async (route: Route) => {
    if (route.request().method() !== "GET") return route.fallback();
    return route.fulfill({
      json: {
        sessions: [
          {
            session_id: "s-next",
            occurrence_id: "occ-next",
            title: "Junior C",
            location: "Court 3",
            start_at: nextStart,
            end_at: new Date(Date.parse(nextStart) + HOUR).toISOString(),
          },
        ],
      },
    });
  });
}

test.describe("Coach Today empty state", () => {
  test("shows the next class and the latest unfinished recap", async ({
    page,
    mock,
  }) => {
    void mock; // installs the stubbed API
    await stubPastAndNextClass(page);

    await page.goto("/coach/today");
    await expect(page.getByTestId("empty-state")).toBeVisible();

    const next = page.getByTestId("next-class");
    await expect(next).toContainText("Your next class");
    await expect(next).toContainText("Junior C");
    await expect(next).toContainText("Court 3");
    await expect(next).toHaveAttribute(
      "href",
      /\/coach\/sessions\/occ-next\?date=\d{4}-\d{2}-\d{2}$/,
    );

    const recap = page.getByTestId("unfinished-recap");
    await expect(recap).toContainText("Finish your class recap");
    await expect(recap).toContainText("Junior B");
    await expect(recap).toHaveAttribute(
      "href",
      /\/coach\/sessions\/occ-past\?date=\d{4}-\d{2}-\d{2}&recap=open$/,
    );
  });

  test("an assistant sees the next class but no recap shortcut", async ({
    page,
    mock,
  }) => {
    mock.me = {
      user_id: "user-assistant-e2e",
      email: "helper@example.com",
      academy_id: "academy-e2e",
      roles: ["assistant_coach"],
    };
    await stubPastAndNextClass(page);

    await page.goto("/coach/today");
    await expect(page.getByTestId("empty-state")).toBeVisible();
    await expect(page.getByTestId("next-class")).toContainText("Junior C");
    await expect(page.getByTestId("unfinished-recap")).toHaveCount(0);
  });

  test("a class with a saved recap gets no shortcut", async ({
    page,
    mock,
  }) => {
    void mock; // installs the stubbed API
    await page.route("**/api/v2/coach/today*", async (route: Route) => {
      if (route.request().method() !== "GET") return route.fallback();
      const date = new URL(route.request().url()).searchParams.get("date");
      const past = new Date(Date.now() - 20 * HOUR).toISOString();
      const sessions =
        date === localISO(-1)
          ? [
              {
                session_id: "s-past",
                occurrence_id: "occ-past",
                title: "Junior B",
                location: "Court 2",
                start_at: past,
                end_at: past,
                roster: [
                  {
                    student_id: "st9",
                    full_name: "Casey Test",
                    enrollment_status: "active",
                  },
                ],
                recap_saved: true,
              },
            ]
          : [];
      return route.fulfill({ json: { date, sessions } });
    });
    await page.route("**/api/v2/coach/sessions", (route: Route) =>
      route.fulfill({ json: { sessions: [] } }),
    );

    await page.goto("/coach/today");
    await expect(page.getByTestId("empty-state")).toBeVisible();
    await expect(page.getByTestId("unfinished-recap")).toHaveCount(0);
    await expect(page.getByTestId("next-class")).toHaveCount(0);
  });
});

test.describe("Class steps", () => {
  test("attendance links to skills, and skills links back to an open recap", async ({
    page,
    mock,
  }) => {
    void mock; // installs the stubbed API
    await page.goto("/coach/sessions/occ-today-1");
    await expect(page.getByTestId("session-detail")).toBeVisible();
    const toSkills = page.getByTestId("next-step-skills");
    await expect(toSkills).toHaveAttribute(
      "href",
      /\/coach\/sessions\/occ-today-1\/skills\?date=/,
    );

    await toSkills.click();
    await expect(page.getByTestId("coach-session-skills")).toBeVisible();
    const toRecap = page.getByTestId("next-step-recap");
    await expect(toRecap).toHaveAttribute(
      "href",
      /\/coach\/sessions\/occ-today-1\?date=.*&recap=open$/,
    );

    await toRecap.click();
    await expect(page.getByTestId("class-recap-toggle")).toHaveAttribute(
      "aria-expanded",
      "true",
    );
  });
});

test.describe("Class sync status", () => {
  test("a queued mark shows Waiting to sync across a reload, then Saved after one send", async ({
    page,
    mock,
  }) => {
    // Server down: the mark stays queued through the reload.
    mock.attendanceResponder = () => ({
      status: 503,
      body: { error: { code: "Unavailable", message: "down", details: {} } },
    });
    await page.goto("/coach/sessions/s-today-1");
    await expect(page.getByTestId("session-detail")).toBeVisible();
    await expect(page.getByTestId("sync-status")).toHaveCount(0); // nothing marked yet

    await page.evaluate(() => window.dispatchEvent(new Event("offline")));
    await page.getByTestId("mark-st1-present").click();
    await expect(page.getByTestId("sync-status")).toHaveText(/Waiting to sync/);

    await page.reload();
    await expect(page.getByTestId("session-detail")).toBeVisible();
    await expect(page.getByTestId("sync-status")).toHaveText(/Waiting to sync/);
    await expect(page.getByTestId("mark-queued-st1")).toBeVisible();

    // Server back: the next reconnect sends it.
    const accepted: string[] = [];
    mock.attendanceResponder = (body) => {
      accepted.push(String(body.mutation_id));
      return {
        status: 200,
        body: {
          attendance_id: body.mutation_id,
          occurrence_id: body.occurrence_id,
          session_id: body.session_id,
          student_id: body.student_id,
          status: body.status,
          marked_at: new Date().toISOString(),
        },
      };
    };
    await page.evaluate(() => window.dispatchEvent(new Event("online")));
    await expect(page.getByTestId("sync-status")).toHaveText(/Saved/, {
      timeout: 15_000,
    });
    await expect(page.getByTestId("mark-queued-st1")).toHaveCount(0);

    // Exactly one accepted send, and every attempt carried the same key.
    expect(accepted).toHaveLength(1);
    const keys = new Set(mock.attendanceCalls.map((c) => c.mutation_id));
    expect(keys.size).toBe(1);
  });

  test("a mark the server rejects shows Needs attention", async ({
    page,
    mock,
  }) => {
    mock.attendanceResponder = () => ({
      status: 409,
      body: {
        error: {
          code: "Coaching.StudentNotEnrolled",
          message: "not enrolled",
          details: {},
        },
      },
    });
    await page.goto("/coach/sessions/s-today-1");
    await expect(page.getByTestId("session-detail")).toBeVisible();
    await page.evaluate(() => window.dispatchEvent(new Event("offline")));
    await page.getByTestId("mark-st1-present").click();
    await expect(page.getByTestId("mark-queued-st1")).toBeVisible();
    await page.evaluate(() => window.dispatchEvent(new Event("online")));
    const status = page.getByTestId("sync-status");
    await expect(status).toHaveText(/Needs attention/);
    await expect(status.getByRole("link")).toHaveAttribute(
      "href",
      "/coach/needs-review",
    );
  });
});
