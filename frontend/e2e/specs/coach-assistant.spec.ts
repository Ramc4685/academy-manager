/**
 * Assistant coach shell.
 *
 * An `assistant_coach` rides the coach shell scoped to the sessions that list
 * them: attendance, skills and notes stay; messaging, announcements, billing
 * previews and pay are lead-coach surfaces and are not rendered. The same
 * fixture also proves a real coach keeps every one of those controls, so the
 * gating is conditional rendering for assistants only, not a regression.
 */

import type { Page } from "@playwright/test";

import { test, expect } from "../fixtures/mock-api";

const PROFILE = {
  user_id: "user-assistant-e2e",
  display_name: "Asha Assistant",
  email: "helper@example.com",
  phone: null,
};

async function stubProfile(page: Page) {
  await page.route("**/api/v2/coach/profile", (route) => {
    if (route.request().method() !== "GET") return route.fallback();
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(PROFILE),
    });
  });
}

/** Lead-only coach endpoints: record every call so a spec can prove none fired. */
function trackLeadOnlyCalls(page: Page): string[] {
  const calls: string[] = [];
  page.on("request", (request) => {
    const url = request.url();
    if (/\/api\/v2\/coach\/messages/.test(url) || /\/api\/v2\/coach\/.*announcements/.test(url)) {
      calls.push(url);
    }
  });
  return calls;
}

test.describe("Assistant coach shell", () => {
  test.beforeEach(async ({ page, mock }) => {
    mock.me = {
      user_id: PROFILE.user_id,
      email: PROFILE.email,
      academy_id: "academy-e2e",
      roles: ["assistant_coach"],
    };
    await stubProfile(page);
  });

  test("today shows the assistant banner and no Messages link", async ({ page }) => {
    const leadOnlyCalls = trackLeadOnlyCalls(page);
    await page.goto("/coach/today");
    await expect(page.getByTestId("coach-today")).toBeVisible();
    await expect(page.getByTestId("coach-assistant-banner")).toContainText(
      "Assistant coach.",
    );
    await expect(page.getByTestId("coach-supervisor-banner")).toHaveCount(0);
    await expect(page.getByTestId("nav-messages")).toHaveCount(0);
    await expect(page.getByTestId("session-s-today-1")).toContainText("Junior A");
    expect(leadOnlyCalls).toEqual([]);
  });

  test("session detail keeps attendance and notes, hides announcements and billing", async ({
    page,
    mock,
  }) => {
    const leadOnlyCalls = trackLeadOnlyCalls(page);
    await page.goto("/coach/sessions/s-today-1");
    await expect(page.getByTestId("session-detail")).toBeVisible();
    await expect(page.getByTestId("mark-st1-present")).toBeVisible();
    await expect(page.getByTestId("mark-all-present")).toBeVisible();
    await expect(page.getByTestId("billing-toggle-st1")).toHaveCount(0);
    await expect(page.getByRole("heading", { name: "Announcements" })).toHaveCount(0);

    await page.getByTestId("mark-st1-present").click();
    await expect.poll(() => mock.attendanceCalls.length).toBe(1);
    expect(mock.attendanceCalls[0]).toMatchObject({
      session_id: "s-today-1",
      student_id: "st1",
      status: "present",
    });
    expect(leadOnlyCalls).toEqual([]);
  });

  test("notes stay private: no share switch, no toggle, private default on save", async ({
    page,
    mock,
  }) => {
    mock.progressNotes.push({
      note_id: "note-lead",
      session_id: "s-today-1",
      student_id: "st1",
      coach_id: "user-coach-e2e",
      body: "Lead coach note",
      created_at: new Date().toISOString(),
      visibility: "shared",
    });
    await page.goto("/coach/sessions/s-today-1");
    await page.getByTestId("roster-st1").getByRole("button", { name: "Note", exact: true }).click();
    await expect(page.getByTestId("note-private-hint")).toContainText(
      "stay private to coaches",
    );
    await expect(page.getByTestId("note-share-st1")).toHaveCount(0);
    // Existing notes still list with their audience, but nothing can flip it.
    await expect(page.getByTestId("note-visibility-note-lead")).toHaveText(/shared with parent/i);
    await expect(page.getByTestId("note-share-toggle-note-lead")).toHaveCount(0);

    await page.getByPlaceholder("Progress note for Alice…").fill("Worked on grip");
    await page.getByRole("button", { name: "Save note" }).click();
    await expect.poll(() => mock.progressNoteCalls.length).toBe(1);
    expect(mock.progressNoteCalls[0]).toEqual({
      student_id: "st1",
      body: "Worked on grip",
      visibility: "private",
    });
  });

  test("skill notes panel has no share control for an assistant", async ({ page, mock }) => {
    mock.skillNotes.push({
      note_id: "skill-note-lead",
      academy_id: "academy-e2e",
      student_id: "st1",
      skill_id: "skill-backhand",
      coach_id: "user-coach-e2e",
      session_id: null,
      body: "Backhand improving",
      created_at: new Date().toISOString(),
      visibility: "private",
    });
    await page.goto("/coach/students/st1/passport?student_name=Alice");
    await expect(page.getByTestId("coach-student-passport")).toBeVisible();
    await page.getByTestId("passport-skill-skill-backhand").getByRole("button", { name: "Notes" }).click();
    await expect(page.getByTestId("skill-note-skill-note-lead")).toContainText("Backhand improving");
    await expect(page.getByTestId("skill-note-private-hint")).toBeVisible();
    await expect(page.getByTestId("skill-note-share")).toHaveCount(0);
    await expect(page.getByTestId("skill-note-share-toggle-skill-note-lead")).toHaveCount(0);

    await page.getByPlaceholder("Add a note about this skill...").fill("Keep the elbow up");
    await page.getByRole("button", { name: "Add Note" }).click();
    await expect.poll(() => mock.skillNoteCalls.length).toBe(1);
    expect(mock.skillNoteCalls[0]).toEqual({
      skill_id: "skill-backhand",
      body: "Keep the elbow up",
      visibility: "private",
    });
  });

  test("profile has no pay card", async ({ page }) => {
    await page.goto("/coach/profile");
    await expect(page.getByTestId("coach-profile")).toBeVisible();
    await expect(page.getByText("Asha Assistant")).toBeVisible();
    await expect(page.getByText("Assistant coach access")).toBeVisible();
    await expect(page.getByTestId("coach-pay-card")).toHaveCount(0);
  });

  test("/coach/messages shows the denied notice instead of an inbox", async ({ page }) => {
    const leadOnlyCalls = trackLeadOnlyCalls(page);
    await page.goto("/coach/messages");
    await expect(page.getByTestId("coach-assistant-denied")).toContainText(
      "Messaging is for the lead coach",
    );
    await expect(page.getByTestId("coach-messages")).toHaveCount(0);
    expect(leadOnlyCalls).toEqual([]);
  });
});

test.describe("Real coach keeps the lead surfaces", () => {
  test("messages link, billing toggle and pay card still render for a coach", async ({
    page,
    mock,
  }) => {
    // Requesting `mock` is what registers the BFF stubs (default persona: coach).
    void mock;
    await stubProfile(page);
    await page.route("**/api/v2/coach/messages", (route) => {
      if (route.request().method() !== "GET") return route.fallback();
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ messages: [] }),
      });
    });

    await page.goto("/coach/sessions/s-today-1");
    await expect(page.getByTestId("session-detail")).toBeVisible();
    await expect(page.getByTestId("coach-assistant-banner")).toHaveCount(0);
    await expect(page.getByTestId("nav-messages")).toBeVisible();
    await expect(page.getByTestId("billing-toggle-st1")).toBeVisible();
    await expect(page.getByRole("heading", { name: "Announcements" })).toBeVisible();

    await page.goto("/coach/profile");
    await expect(page.getByTestId("coach-pay-card")).toBeVisible();
  });
});
