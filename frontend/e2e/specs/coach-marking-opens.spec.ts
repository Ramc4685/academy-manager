/**
 * Marking opens an hour before class. A coach who opens the class screen
 * earlier must see the buttons unlock at T-60 without reloading.
 */

import { test, expect } from "../fixtures/mock-api";

test("the class screen unlocks marking at T-60 without a reload", async ({ page, mock }) => {
  const date = mock.today.date;
  mock.today.sessions[0].start_at = `${date}T12:00:00Z`;
  mock.today.sessions[0].end_at = `${date}T13:30:00Z`;
  await page.clock.install({ time: new Date(`${date}T10:30:00Z`) });

  await page.goto("/coach/sessions/s-today-1");
  await expect(page.getByTestId("marking-not-open")).toBeVisible();
  await expect(page.getByTestId("mark-st1-present")).toBeDisabled();
  // The banner and the disabled bulk button name the same opening time: T-60
  // in the class's zone, never "when class starts" (usability study).
  const opensAt = await page.getByTestId("marking-not-open").textContent();
  const time = /opens at (\d{1,2}:\d{2} [AP]M \S+),/.exec(opensAt ?? "")?.[1];
  expect(time).toBeTruthy();
  await expect(page.getByTestId("mark-all-present")).toHaveText(`Opens at ${time}`);
  await expect(page.getByTestId("session-when")).toContainText(/\w{3}, \w{3} \d{1,2} · /);

  // 31 minutes later the class is 59 minutes away: marking is open.
  await page.clock.fastForward("31:00");
  await expect(page.getByTestId("marking-not-open")).toHaveCount(0);
  await expect(page.getByTestId("mark-st1-present")).toBeEnabled();
});
