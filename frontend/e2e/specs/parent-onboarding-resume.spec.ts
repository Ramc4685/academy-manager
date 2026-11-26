/**
 * S21 / S02: "Finish registration" resumes that application on the first step
 * still to fill in, the step is kept in the URL, and a reload stays put.
 * Mocks the v2 BFF at the Playwright route layer. Names are fake.
 */

import { expect, test } from "@playwright/test";

import {
  ACADEMY_A,
  fulfillJson,
  stubMe,
  stubMemberships,
  stubParentAcademy,
  stubParentMessages,
  stubParentProfile,
} from "../fixtures/saas-stubs";

const APPLICATION = {
  application_id: "app-mateo",
  status: "DRAFT",
  parent_profile: {
    first_name: "Ana",
    last_name: "Rivera",
    email: "new.parent@example.com",
    phone: "555-0142",
  },
  child_profile: {
    first_name: "Mateo",
    last_name: "Rivera",
    date_of_birth: "",
    skill_level: "",
    emergency_contact_name: "",
    emergency_contact_phone: "",
    medical_notes: "",
  },
  selected_session_id: null,
  waiver_accepted: false,
  waiver_class_first: false,
  expires_at: "2027-05-27T00:00:00Z",
};

test("Finish registration resumes the card's application on its next step", async ({ page }) => {
  const started: Array<string | null> = [];
  await stubMe(page, {
    user_id: "user-parent-resume",
    email: "new.parent@example.com",
    academy_id: ACADEMY_A,
    roles: ["parent"],
  });
  await stubMemberships(page, [
    { academy_id: ACADEMY_A, academy_name: "Academy A", role: "parent" },
  ]);
  await stubParentProfile(page, { user_id: "user-parent-resume" });
  await stubParentMessages(page);
  await stubParentAcademy(page);
  await page.route("**/api/v2/parent/invoices", (route) => {
    if (route.request().method() !== "GET") return route.fallback();
    return fulfillJson(route, { invoices: [] });
  });
  await page.route("**/api/v2/parent/sessions/available", (route) =>
    fulfillJson(route, { sessions: [] }),
  );
  await page.route("**/api/v2/parent/onboarding/start", (route) => {
    if (route.request().method() !== "POST") return route.fallback();
    const body = JSON.parse(route.request().postData() ?? "{}") as { application_id?: string };
    started.push(body.application_id ?? null);
    return fulfillJson(route, APPLICATION);
  });

  await page.goto(`/parent/onboarding?application=${APPLICATION.application_id}`);
  await expect(page.getByRole("heading", { name: "Your child" })).toBeVisible();
  await expect(page).toHaveURL(/[?&]step=child\b/);
  await expect(page.getByLabel("First name")).toHaveValue("Mateo");

  await page.reload();
  await expect(page.getByRole("heading", { name: "Your child" })).toBeVisible();
  expect(started.every((id) => id === APPLICATION.application_id)).toBe(true);
});
