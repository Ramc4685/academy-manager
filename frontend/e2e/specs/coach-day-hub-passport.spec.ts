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

    await page.getByRole("link", { name: "Open skill updates" }).click();
    await page.waitForLoadState("networkidle");
    await expect(page.getByTestId("coach-session-skills")).toBeVisible();
    await expect(page.getByRole("button", { name: "By skill" })).toBeVisible();
    await page.getByRole("button", { name: "Update selected students" }).click();
    await expect.poll(() => mock.bulkSkillCalls.length).toBe(1);

    await page.getByRole("button", { name: "By student" }).click();
    await expect(page.getByLabel("Student")).toBeVisible();
    await expect(page.getByText("Backhand clear")).toBeVisible();
    await page.getByRole("button", { name: "Save" }).first().click();
    await expect.poll(() => mock.skillStatusCalls.length).toBe(1);
    await page.waitForLoadState("networkidle");

    // After invalidateQueries the App Router occasionally issues a soft re-navigation
    // back to the current skills URL. Catch it and retry so the test never needs a
    // Playwright-level retry (which would trip failOnFlakyTests in CI).
    const passportUrl = "/coach/students/st1/passport?program_id=prog-001&from_session=s-today-1&student_name=Alice";
    await page.goto(passportUrl).catch(async (e: Error) => {
      if (!e.message.includes("interrupted")) throw e;
      await page.waitForLoadState("networkidle");
      await page.goto(passportUrl);
    });
    await expect(page.getByTestId("coach-student-passport")).toBeVisible();
    await expect(page.getByText("Backhand clear")).toBeVisible();

    await page.goto("/coach/dashboard");
    await page.getByRole("button", { name: "Message parents" }).click();
    await expect(page.getByRole("status")).toContainText(
      "Parent messaging needs the coach-scoped messaging service"
    );
    await expect(page.getByRole("status")).not.toContainText("404");

    await page.getByRole("button", { name: "I can't attend" }).click();
    await expect(page.getByRole("status")).toContainText(
      "Absence notices need a coach-scoped replacement request workflow"
    );
    await expect(page.getByRole("status")).not.toContainText("500");

    await page.getByRole("link", { name: "Prepare" }).click();
    await expect(page.getByTestId("coach-teaching-plan")).toBeVisible();
    await expect(page.getByRole("heading", { name: "Lesson 3: Overhead Clear" })).toBeVisible();
  });
});
