/**
 * Parent drop-off check-in, stubbed at the route layer (fixtures/mock-api.ts).
 *
 *  - Parent: "I've arrived" shows only inside the server's window, sends one
 *    request for one child (siblings untouched), survives a reload from server
 *    state, and an offline tap says staff were NOT told — and is never
 *    replayed when the phone reconnects; Retry re-sends it.
 *  - Coach: the arrived badge is not a Present mark; one tap confirms and the
 *    server's single mark shows, with no extra attendance POST.
 *  - Admin: Expected / Arrived / Checked-in breakdown, Confirm drop-off, and
 *    who reported / confirmed at what academy time.
 *  - Feature off: no button anywhere; manual marking works as before.
 */

import type { Page, Route } from "@playwright/test";

import { test, expect } from "../fixtures/mock-api";

const MIN = 60_000;
const TZ = "America/Chicago";
const AVA = { student_id: "st-ava", full_name: "Ava Test" };
const BEN = { student_id: "st-ben", full_name: "Ben Test" };

function iso(offsetMs: number): string {
  return new Date(Date.now() + offsetMs).toISOString();
}

type State = "none" | "pending" | "confirmed" | "expired";

function checkinView(studentId: string, occurrenceId: string, state: State, canReport: boolean) {
  return {
    occurrence_id: occurrenceId,
    student_id: studentId,
    state,
    reported_at: state === "none" ? null : iso(-2 * MIN),
    confirmed_at: state === "confirmed" ? iso(-1 * MIN) : null,
    window_opens_at: iso(-20 * MIN),
    window_closes_at: iso(25 * MIN),
    can_report_arrival: canReport,
  };
}

async function stubInboxes(page: Page) {
  await page.route(/\/api\/v2\/(parent|coach)\/messages/, (route) =>
    route.fulfill({ json: { messages: [] } }),
  );
}

/**
 * A tiny parent backend: one class today (window open) per child plus Ava's
 * class tomorrow (window shut). Arrival state lives here, so a reload reads
 * what the "server" saved.
 */
async function stubParent(page: Page, opts: { enabled?: boolean } = {}) {
  const enabled = opts.enabled ?? true;
  const reported = new Map<string, State>();
  const arrivalPosts: string[] = [];
  let failNext = false;
  // Route stubs still answer while the context is offline, so model an
  // unreachable server here: the request never arrives and is not recorded.
  let unreachable = false;

  await page.route("**/api/v2/parent/academy", (route) =>
    route.fulfill({
      json: {
        display_name: "Aces Academy",
        timezone: TZ,
        contact_email: null,
        contact_phone: null,
        hours_text: null,
        address: null,
        logo_url: null,
        brand_color: null,
        notice_window_met: true,
        self_service: {
          can_report_absence: true,
          can_request_makeup: true,
          can_request_pause: true,
          can_request_cancel: true,
          can_claim_waitlist_offer: true,
          can_request_trial: true,
          dropoff_checkin_enabled: enabled,
        },
      },
    }),
  );
  await page.route("**/api/v2/parent/children", (route) =>
    route.fulfill({
      json: {
        children: [AVA, BEN].map((c) => ({
          ...c,
          lifecycle: "active",
          active_session_count: 1,
          attended_count: 0,
          absent_count: 0,
        })),
      },
    }),
  );
  await page.route("**/api/v2/parent/attendance", (route) => route.fulfill({ json: { records: [] } }));
  await page.route("**/api/v2/parent/enrollments", (route) =>
    route.fulfill({ json: { enrollments: [] } }),
  );
  await page.route("**/api/v2/parent/children/*/schedule*", (route) => {
    const studentId = new URL(route.request().url()).pathname.split("/")[5];
    const entry = (occurrenceId: string, title: string, start: string, open: boolean) => {
      const state = reported.get(`${studentId}/${occurrenceId}`) ?? "none";
      const canReport = enabled && open && state === "none";
      return {
        occurrence_id: occurrenceId,
        session_id: `sess-${occurrenceId}`,
        session_title: title,
        location: "Court 1",
        start_at: start,
        end_at: iso(70 * MIN),
        status: "scheduled",
        coach_name: "Coach Sam",
        absence_reported: false,
        checkin: enabled ? checkinView(studentId, occurrenceId, state, canReport) : null,
        can_report_arrival: canReport,
      };
    };
    const entries = [entry(`occ-today-${studentId}`, "Junior A", iso(10 * MIN), true)];
    if (studentId === AVA.student_id) {
      entries.push(entry("occ-tomorrow", "Junior A", iso(26 * 60 * MIN), false));
    }
    return route.fulfill({ json: { entries, total: entries.length, limit: 20, offset: 0 } });
  });
  await page.route("**/api/v2/parent/children/*/occurrences/*/arrival", (route: Route) => {
    if (route.request().method() !== "POST") return route.fallback();
    const parts = new URL(route.request().url()).pathname.split("/");
    const studentId = parts[5];
    const occurrenceId = parts[7];
    if (unreachable) return route.abort("internetdisconnected");
    arrivalPosts.push(`${studentId}/${occurrenceId}`);
    if (failNext) {
      failNext = false;
      return route.abort("internetdisconnected");
    }
    reported.set(`${studentId}/${occurrenceId}`, "pending");
    return route.fulfill({ json: checkinView(studentId, occurrenceId, "pending", false) });
  });

  return {
    arrivalPosts,
    reported,
    failNextPost: () => {
      failNext = true;
    },
    setUnreachable: (value: boolean) => {
      unreachable = value;
    },
  };
}

test.describe("parent drop-off check-in", () => {
  test.beforeEach(async ({ page, mock }) => {
    mock.me = { ...mock.me, user_id: "user-parent-e2e", roles: ["parent"] };
    await stubInboxes(page);
  });

  test("reports one sibling, leaves the other alone, hides closed windows and survives a reload", async ({
    page,
  }) => {
    const backend = await stubParent(page);
    await page.goto("/parent/children");

    const avaToday = `arrival-${AVA.student_id}-occ-today-${AVA.student_id}`;
    const benToday = `arrival-${BEN.student_id}-occ-today-${BEN.student_id}`;
    await expect(page.getByTestId(`${avaToday}-report`)).toBeVisible();
    await expect(page.getByTestId(`${benToday}-report`)).toBeVisible();
    // Tomorrow's class is outside the window: no button at all.
    await expect(page.getByTestId(`arrival-${AVA.student_id}-occ-tomorrow-report`)).toHaveCount(0);

    await page.getByRole("button", { name: `I've arrived with ${AVA.full_name} for Junior A` }).click();
    await expect(page.getByTestId(`${avaToday}-pending`)).toHaveText("Arrival sent · Waiting for staff");
    await expect(page.getByTestId(`${benToday}-report`)).toBeVisible();
    expect(backend.arrivalPosts).toEqual([`${AVA.student_id}/occ-today-${AVA.student_id}`]);

    await page.reload();
    await expect(page.getByTestId(`${avaToday}-pending`)).toBeVisible();
    await expect(page.getByTestId(`${benToday}-report`)).toBeVisible();
    expect(backend.arrivalPosts).toHaveLength(1);
  });

  test("an offline tap says staff were not told, is never replayed, and Retry sends it", async ({
    page,
    context,
  }) => {
    const backend = await stubParent(page);
    await page.goto("/parent/children");
    const avaToday = `arrival-${AVA.student_id}-occ-today-${AVA.student_id}`;
    await expect(page.getByTestId(`${avaToday}-report`)).toBeVisible();

    await context.setOffline(true);
    backend.setUnreachable(true);
    await page.getByTestId(`${avaToday}-report`).click();
    await expect(page.getByTestId(`${avaToday}-error`)).toContainText("Staff have NOT received");
    backend.setUnreachable(false);
    await context.setOffline(false);
    // Back online: nothing is sent behind the parent's back.
    await page.waitForTimeout(1500);
    expect(backend.arrivalPosts).toHaveLength(0);
    await expect(page.getByTestId(`${avaToday}-error`)).toBeVisible();

    // A dropped connection mid-request is the same message.
    backend.failNextPost();
    await page.getByTestId(`${avaToday}-retry`).click();
    await expect(page.getByTestId(`${avaToday}-error`)).toContainText("Staff have NOT received");
    expect(backend.arrivalPosts).toHaveLength(1);

    await page.getByTestId(`${avaToday}-retry`).click();
    await expect(page.getByTestId(`${avaToday}-pending`)).toBeVisible();
    expect(backend.arrivalPosts).toHaveLength(2);
  });

  test("a confirmed arrival reads Checked in", async ({ page }) => {
    const backend = await stubParent(page);
    backend.reported.set(`${AVA.student_id}/occ-today-${AVA.student_id}`, "confirmed");
    await page.goto("/parent/children");
    await expect(
      page.getByTestId(`arrival-${AVA.student_id}-occ-today-${AVA.student_id}-confirmed`),
    ).toHaveText("Checked in");
  });

  test("feature off: no arrival button for any child", async ({ page }) => {
    const backend = await stubParent(page, { enabled: false });
    await page.goto("/parent/children");
    await expect(page.getByText("Junior A").first()).toBeVisible();
    await expect(page.getByRole("button", { name: /I've arrived/ })).toHaveCount(0);
    expect(backend.arrivalPosts).toHaveLength(0);
  });
});

test.describe("coach drop-off confirmation", () => {
  test("arrived badge is not Present; one tap confirms with one server mark", async ({ page, mock }) => {
    await stubInboxes(page);
    const session = mock.today.sessions[0];
    session.roster[0].checkin = {
      ...checkinView("st1", session.occurrence_id, "pending", false),
      reported_by: "parent-1",
      reported_by_name: null,
      confirmed_by: null,
      confirmed_by_name: null,
      attendance_id: null,
      reconciled_with_existing_mark: false,
    };
    const confirmCalls: string[] = [];
    await page.route("**/api/v2/coach/occurrences/*/checkins/*/confirm", (route) => {
      if (route.request().method() !== "POST") return route.fallback();
      confirmCalls.push(new URL(route.request().url()).pathname);
      return route.fulfill({
        json: {
          ...checkinView("st1", session.occurrence_id, "confirmed", false),
          reported_by: "parent-1",
          reported_by_name: null,
          confirmed_by: "user-coach-e2e",
          confirmed_by_name: null,
          attendance_id: "dropoff:chk-1",
          reconciled_with_existing_mark: false,
        },
      });
    });

    await page.goto(`/coach/sessions/${session.occurrence_id}`);
    await expect(page.getByTestId("dropoff-pending-st1")).toContainText("ARRIVED · AWAITING CONFIRMATION");
    await expect(page.getByTestId("mark-st1-present")).toHaveAttribute("aria-pressed", "false");
    await expect(page.getByTestId("dropoff-pending-st2")).toHaveCount(0);

    await page.getByRole("button", { name: "Confirm drop-off for Alice" }).click();
    await expect(page.getByTestId("dropoff-confirmed-st1")).toBeVisible();
    await expect(page.getByTestId("mark-st1-present")).toHaveAttribute("aria-pressed", "true");
    await expect(page.getByTestId("confirm-dropoff-st1")).toHaveCount(0);
    expect(confirmCalls).toHaveLength(1);
    // The server wrote the mark; the client sent no attendance of its own.
    expect(mock.attendanceCalls).toHaveLength(0);
  });

  test("feature off: no badge, and manual marking still works", async ({ page, mock }) => {
    await stubInboxes(page);
    await page.goto(`/coach/sessions/${mock.today.sessions[0].occurrence_id}`);
    await expect(page.getByTestId("roster-st1")).toBeVisible();
    await expect(page.getByTestId("dropoff-pending-st1")).toHaveCount(0);
    await page.getByTestId("mark-st1-present").click();
    await expect(page.getByTestId("mark-st1-present")).toHaveAttribute("aria-pressed", "true");
    await expect.poll(() => mock.attendanceCalls.length).toBe(1);
  });
});

test.describe("admin drop-off breakdown", () => {
  const SESSION_ID = "sess-dropoff";
  const OCC_ID = "occ-dropoff";

  test("shows counts and actors, and front-desk staff confirm a pending arrival", async ({ page, mock }) => {
    mock.me = { ...mock.me, user_id: "user-admin-e2e", roles: ["admin", "owner"] };
    const start = iso(-10 * MIN);
    let avaConfirmed = false;
    const confirmCalls: string[] = [];

    await page.route("**/api/v2/me/memberships", (route) =>
      route.fulfill({
        json: {
          memberships: [
            {
              academy_id: "academy-e2e",
              academy_name: "Academy E2E",
              academy_slug: "academy-e2e",
              roles: ["admin", "owner"],
              status: "active",
              is_default: true,
            },
          ],
          active_academy_id: "academy-e2e",
        },
      }),
    );
    await page.route("**/api/v2/admin/**", (route) => {
      const request = route.request();
      const path = new URL(request.url()).pathname;
      if (request.method() !== "GET") return route.fallback();
      if (path === `/api/v2/admin/sessions/${SESSION_ID}`) {
        return route.fulfill({
          json: {
            session_id: SESSION_ID,
            coach_id: "coach-1",
            coach_name: "Coach One",
            title: "Junior A",
            location: "Court 1",
            start_at: start,
            end_at: iso(50 * MIN),
            days_of_week: ["Mon"],
            start_time: "18:00",
            end_time: "19:00",
            timezone: TZ,
            capacity: 12,
            amount_cents: 10000,
            status: "scheduled",
            enrolled_count: 2,
            waitlist_count: 0,
          },
        });
      }
      if (path.endsWith("/enrollments")) {
        return route.fulfill({
          json: {
            enrollments: [AVA, BEN].map((c, i) => ({
              enrollment_id: `enr-${i}`,
              session_id: SESSION_ID,
              student_id: c.student_id,
              parent_id: `parent-${i}`,
              full_name: c.full_name,
              status: "active",
              enrolled_at: "2026-08-01T00:00:00Z",
              dues_status: "current",
            })),
          },
        });
      }
      if (path.endsWith("/occurrences")) {
        return route.fulfill({
          json: {
            occurrences: [
              {
                occurrence_id: OCC_ID,
                session_id: SESSION_ID,
                start_at: start,
                end_at: iso(50 * MIN),
                status: "scheduled",
                cancellation_reason: null,
                cancelled_at: null,
                scheduled_coach_id: "coach-1",
                actual_coach_id: null,
                substitute_coach_id: null,
                attendance_marked_count: 0,
                attendance_marked_by: [],
                attendance_last_marked_at: null,
                coach_attendance: [],
              },
            ],
          },
        });
      }
      if (path.endsWith("/waitlist")) return route.fulfill({ json: { waitlist: [] } });
      if (path === "/api/v2/admin/users") return route.fulfill({ json: { users: [] } });
      if (path.startsWith("/api/v2/admin/messages")) return route.fulfill({ json: { messages: [], unread_count: 0 } });
      return route.fulfill({ json: {} });
    });
    await page.route(`**/api/v2/admin/session-occurrences/${OCC_ID}/attendance`, (route) => {
      if (route.request().method() !== "GET") return route.fallback();
      const staff = (studentId: string, state: State, reporter: string, confirmer: string | null) => ({
        ...checkinView(studentId, OCC_ID, state, false),
        // 5:42 PM / 5:50 PM Chicago on a fixed day so the actor line is exact.
        reported_at: "2026-11-23T23:42:00Z",
        confirmed_at: confirmer ? "2026-11-23T23:50:00Z" : null,
        reported_by: `parent-${studentId}`,
        reported_by_name: reporter,
        confirmed_by: confirmer ? "staff-1" : null,
        confirmed_by_name: confirmer,
        attendance_id: confirmer ? `dropoff:${studentId}` : null,
        reconciled_with_existing_mark: false,
      });
      const ava = avaConfirmed
        ? staff(AVA.student_id, "confirmed", "Pat Test", "Fran Desk")
        : staff(AVA.student_id, "pending", "Pat Test", null);
      const ben = staff(BEN.student_id, "confirmed", "Lee Test", "Coach One");
      const marks = [ben, ...(avaConfirmed ? [ava] : [])].map((c) => ({
        attendance_id: c.attendance_id,
        occurrence_id: OCC_ID,
        session_id: SESSION_ID,
        student_id: c.student_id,
        status: "present",
        previous_status: null,
        corrected_by: null,
        corrected_at: null,
        correction_reason: null,
        marked_by: "staff-1",
        marked_at: c.confirmed_at,
      }));
      return route.fulfill({
        json: {
          attendance: marks,
          dropoff: {
            enabled: true,
            expected_student_ids: [AVA.student_id, BEN.student_id],
            expected_count: 2,
            pending_count: avaConfirmed ? 0 : 1,
            confirmed_count: avaConfirmed ? 2 : 1,
            checkins: [ava, ben],
          },
        },
      });
    });
    await page.route(`**/api/v2/admin/session-occurrences/${OCC_ID}/checkins/*/confirm`, (route) => {
      if (route.request().method() !== "POST") return route.fallback();
      confirmCalls.push(new URL(route.request().url()).pathname);
      avaConfirmed = true;
      return route.fulfill({ json: checkinView(AVA.student_id, OCC_ID, "confirmed", false) });
    });

    await page.goto(`/admin/sessions/${SESSION_ID}`);
    await page.getByRole("button", { name: "Class dates", exact: true }).click();
    // No mark yet, but a drop-off may be waiting: Attendance is offered around class time.
    await page.getByTestId(`attendance-occurrence-${OCC_ID}`).click();

    const breakdown = page.getByTestId("dropoff-breakdown");
    await expect(breakdown.getByTestId("dropoff-expected-count")).toHaveText("2");
    await expect(breakdown.getByTestId("dropoff-pending-count")).toHaveText("1");
    await expect(breakdown.getByTestId("dropoff-confirmed-count")).toHaveText("1");
    await expect(page.getByTestId(`dropoff-actors-${BEN.student_id}`)).toHaveText(
      "Reported by Lee Test at 5:42 PM CST · Confirmed by Coach One at 5:50 PM CST",
    );
    await expect(page.getByTestId(`dropoff-actors-${AVA.student_id}`)).toHaveText(
      "Reported by Pat Test at 5:42 PM CST",
    );

    await page.getByRole("button", { name: `Confirm drop-off for ${AVA.full_name}` }).click();
    await expect(breakdown.getByTestId("dropoff-confirmed-count")).toHaveText("2");
    await expect(page.getByTestId(`dropoff-actors-${AVA.student_id}`)).toHaveText(
      "Reported by Pat Test at 5:42 PM CST · Confirmed by Fran Desk at 5:50 PM CST",
    );
    await expect(page.getByTestId(`confirm-dropoff-${AVA.student_id}`)).toHaveCount(0);
    expect(confirmCalls).toEqual([
      `/api/v2/admin/session-occurrences/${OCC_ID}/checkins/${AVA.student_id}/confirm`,
    ]);
  });
});
