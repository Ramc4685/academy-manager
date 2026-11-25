/**
 * The Attendance header names the class's own date (usability study: a coach
 * opened the wrong class of two on one day). The date comes from the occurrence
 * in the academy's zone, never from the recurring schedule: a one-off Wednesday
 * class under a Saturday schedule reads Wednesday, also after a reload.
 */

import type { Page } from "@playwright/test";

import { test, expect } from "../fixtures/mock-api";

async function expectWednesdayHeader(page: Page, date: string): Promise<void> {
  await page.goto(`/coach/sessions/s-today-1?date=${date}`);
  const when = page.getByTestId("session-when");
  // 22:00Z on Wed Nov 18 is 4:00 PM in Chicago (CST).
  await expect(when).toContainText("Wed, Nov 18");
  await expect(when).toContainText("4:00 PM");
  await expect(when).toContainText("CST");
  await expect(page.getByTestId("session-detail")).toContainText("Court 1");
  await page.reload();
  await expect(page.getByTestId("session-when")).toContainText("Wed, Nov 18");
}

for (const viewport of [
  { name: "phone", size: { width: 400, height: 860 } },
  { name: "desktop", size: { width: 1280, height: 800 } },
]) {
  test(`a one-off Wednesday class shows Wednesday in the header (${viewport.name})`, async ({
    page,
    mock,
  }) => {
    await page.setViewportSize(viewport.size);
    const session = mock.today.sessions[0] as (typeof mock.today.sessions)[0] & {
      timezone?: string;
      days_of_week?: string[];
    };
    session.title = "Junior Beginners";
    session.location = "Court 1";
    session.start_at = "2026-11-18T22:00:00Z";
    session.end_at = "2026-11-18T23:00:00Z";
    session.timezone = "America/Chicago";
    session.days_of_week = ["Sat"]; // the recurring schedule says Saturday
    await expectWednesdayHeader(page, mock.today.date);
  });
}
