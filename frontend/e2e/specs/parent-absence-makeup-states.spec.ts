/**
 * Parent absence → makeup states: each reported absence on Requests →
 * Absences shows the server-derived makeup state (Reported, Makeup eligible,
 * Makeup booked with the class, Makeup expired), and an eligible one links
 * straight to the Makeups tab with that class pre-selected.
 *
 * Mocks the v2 BFF at the Playwright route layer, like
 * parent-self-service.spec.ts. Names are fake.
 */

import { test, expect } from "../fixtures/mock-api";
import type { Page, Route } from "@playwright/test";

const KID = "st-1";
const KID_NAME = "Mira Testwell";

function json(route: Route, body: unknown) {
  return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
}

function klass(occurrenceId: string, title: string, startAt: string) {
  const end = new Date(new Date(startAt).getTime() + 3_600_000).toISOString();
  return {
    occurrence_id: occurrenceId,
    session_id: "sess-1",
    session_title: title,
    start_at: startAt,
    end_at: end,
    timezone: "America/Chicago",
    status: "scheduled",
  };
}

function notice(occurrenceId: string, startAt: string, makeup: Record<string, unknown>) {
  return {
    notice_id: `n-${occurrenceId}`,
    student_id: KID,
    occurrence_id: occurrenceId,
    session_id: "sess-1",
    submitted_by: "parent-1",
    submitted_at: "2026-11-01T12:00:00Z",
    notice_window_met: true,
    missed_class: klass(occurrenceId, "Junior Beginners", startAt),
    makeup,
  };
}

async function stubParent(page: Page): Promise<void> {
  await page.route("**/api/v2/me", (route) =>
    route.request().method() !== "GET"
      ? route.fallback()
      : json(route, {
          user_id: "user-parent-e2e",
          email: "parent@example.com",
          academy_id: "academy-e2e",
          roles: ["parent"],
        }),
  );
  await page.route("**/api/v2/parent/waitlist", (route) => json(route, { entries: [] }));
  await page.route("**/api/v2/parent/academy", (route) =>
    json(route, {
      display_name: "Test Racquet Club",
      timezone: "America/Chicago",
      contact_email: null,
      contact_phone: null,
      hours_text: null,
      address: null,
      logo_url: null,
    }),
  );
  await page.route("**/api/v2/parent/children", (route) =>
    json(route, {
      children: [
        {
          student_id: KID,
          full_name: KID_NAME,
          lifecycle: "active",
          active_session_count: 1,
          attended_count: 4,
          absent_count: 3,
        },
      ],
    }),
  );
  await page.route(`**/api/v2/parent/children/${KID}/schedule*`, (route) =>
    json(route, { entries: [], total: 0, limit: 50, offset: 0 }),
  );
  await page.route("**/api/v2/parent/absences", (route) =>
    route.request().method() !== "GET"
      ? route.fallback()
      : json(route, {
          notices: [
            notice("occ-up", "2026-12-05T15:00:00Z", { state: "reported" }),
            notice("occ-elig", "2026-11-14T15:00:00Z", {
              state: "eligible",
              expires_at: "2026-12-14T15:00:00Z",
            }),
            notice("occ-booked", "2026-11-07T15:00:00Z", {
              state: "booked",
              booked_class: klass("occ-target", "Saturday Juniors", "2026-11-28T16:00:00Z"),
            }),
            notice("occ-old", "2026-09-26T15:00:00Z", { state: "expired" }),
          ],
        }),
  );
  await page.route("**/api/v2/parent/makeups/candidates", (route) =>
    json(route, {
      makeups_enabled: true,
      requires_notice: true,
      ineligible: [],
      candidates: [
        {
          student_id: KID,
          student_name: KID_NAME,
          occurrence_id: "occ-elig",
          session_id: "sess-1",
          class_title: "Junior Beginners",
          start_at: "2026-11-14T15:00:00Z",
          end_at: "2026-11-14T16:00:00Z",
          has_notice: true,
          expires_at: "2026-12-14T15:00:00Z",
        },
      ],
    }),
  );
  await page.route("**/api/v2/parent/makeups/eligible-targets*", (route) =>
    json(route, { targets: [] }),
  );
  await page.route("**/api/v2/parent/makeups", (route) =>
    route.request().method() !== "GET" ? route.fallback() : json(route, { makeups: [] }),
  );
}

test.describe("parent absences — makeup states", () => {
  test("each reported absence shows its makeup state, and eligible links to booking", async ({
    page,
  }) => {
    await stubParent(page);
    await page.goto("/parent/requests");

    const state = (occ: string) => page.getByTestId(`absence-makeup-${KID}-${occ}`);
    await expect(state("occ-up")).toContainText("REPORTED");
    await expect(state("occ-up").getByRole("link")).toHaveCount(0);
    await expect(state("occ-elig")).toContainText("MAKEUP ELIGIBLE");
    await expect(state("occ-elig")).toContainText(/Request a makeup by .*Dec 14/);
    await expect(state("occ-booked")).toContainText("MAKEUP BOOKED");
    await expect(state("occ-booked")).toContainText("Saturday Juniors — Sat, Nov 28");
    await expect(state("occ-booked").getByRole("link")).toHaveCount(0);
    await expect(state("occ-old")).toContainText("MAKEUP EXPIRED");
    await expect(state("occ-old").getByRole("link")).toHaveCount(0);

    const book = state("occ-elig").getByRole("link", { name: "Book a makeup" });
    await expect(book).toHaveAttribute("href", "/parent/requests?tab=makeups&makeup=st-1%3Aocc-elig");
    const makeupsTab = page.getByRole("tab", { name: "Makeups" });
    for (const attempt of [1, 2]) {
      await book.click();
      await expect(makeupsTab, `attempt ${attempt}`).toHaveAttribute("aria-selected", "true");
      await expect(page.getByLabel("Missed class")).toHaveValue(`${KID}:occ-elig`);
      await expect(page.getByRole("button", { name: "Request makeup" })).toBeEnabled();
      // The link is consumed, so the same link clicked again still navigates.
      await expect(page).toHaveURL(/\/parent\/requests$/);
      await page.getByRole("tab", { name: "Absences" }).click();
    }
  });
});
