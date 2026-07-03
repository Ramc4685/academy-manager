import { test, expect } from "../fixtures/mock-api";

test.describe("Coach Day Hub and Skill Passport", () => {
  test.describe.configure({ mode: "serial" });

  test("covers day hub, future date controls, skills workspace, passport, and prep link", async ({
    page,
    mock,
  }) => {
    await page.goto("/coach/dashboard");

    await expect(page.getByTestId("coach-day-hub")).toBeVisible();
    await expect(page.getByText("Coach Day Hub")).toBeVisible();
    await expect(page.getByText("Expected cut")).toHaveCount(0);
    await expect(page.getByText("Backhand clear")).toBeVisible();

    await page.getByRole("button", { name: "Tomorrow" }).click();
    await expect(page.getByText("Junior A")).toBeVisible();
    await page.getByRole("button", { name: "Today" }).click();

    await Promise.all([
      page.waitForURL(/\/coach\/sessions\/occ-today-1\?date=\d{4}-\d{2}-\d{2}$/),
      page.getByRole("link", { name: "Open session" }).click(),
    ]);
    await expect(page.getByTestId("session-detail")).toBeVisible();
    await Promise.all([
      page.waitForURL(/\/coach\/students\/st1\/passport\?/),
      page.getByTestId("roster-st1").getByRole("link", { name: "Skills" }).click(),
    ]);
    await expect(page.getByTestId("coach-student-passport")).toBeVisible();
    await expect(page.getByText("Backhand clear")).toBeVisible();

    await page.goto("/coach/dashboard", { waitUntil: "domcontentloaded" });
    await expect(page.getByTestId("coach-day-hub")).toBeVisible();

    const skillUpdatesLink = page.getByRole("link", { name: "Open skill updates" });
    await Promise.all([
      page.waitForURL(/\/coach\/sessions\/occ-today-1\/skills\?date=\d{4}-\d{2}-\d{2}$/),
      skillUpdatesLink.click(),
    ]);
    await expect(page.getByTestId("coach-session-skills")).toBeVisible();
    await expect(page.getByRole("button", { name: "By skill" })).toBeVisible();
    await page.getByRole("button", { name: "Update selected students" }).click();
    await expect.poll(() => mock.bulkSkillCalls.length).toBe(1);

    await page.getByRole("button", { name: "By student" }).click();
    await expect(page.getByLabel("Student")).toBeVisible();
    await expect(page.getByText("Backhand clear")).toBeVisible();
    await page.getByRole("button", { name: "Save" }).first().click();
    await expect
      .poll(() => mock.skillStatusCalls.length, {
        message: "wait for the skill status mutation to settle before leaving",
      })
      .toBe(1);

    await page.goto("/coach/dashboard");
    await expect(page.getByTestId("coach-day-hub")).toBeVisible();
    // Dead placeholder actions must not ship: no coach-scoped messaging or
    // absence workflow exists yet, so these buttons were removed.
    await expect(page.getByRole("button", { name: "Message parents" })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "I can't attend" })).toHaveCount(0);

    await Promise.all([
      page.waitForURL(/\/coach\/today\/plan\?date=\d{4}-\d{2}-\d{2}$/),
      page.getByRole("link", { name: "Prepare" }).click(),
    ]);
    await expect(page.getByTestId("coach-teaching-plan")).toBeVisible();
    await expect(page.getByRole("heading", { name: "Lesson 3: Overhead Clear" })).toBeVisible();
  });
});
