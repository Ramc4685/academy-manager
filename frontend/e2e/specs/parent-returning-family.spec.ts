/**
 * Returning-family re-enrolment through onboarding (#827, from #775).
 *
 * The departed row on /parent/children links here with the child pinned to
 * the url (covered in parent-self-service.spec.ts). What this spec guards is
 * the other half of the promise: the child step offers the student the family
 * ALREADY has, with the name and date of birth the backend binds on — so
 * coming back joins the existing record instead of forking the child in two.
 *
 * Mocks the v2 BFF at the Playwright route layer, like the other parent
 * specs; every call the parent shell makes is stubbed so an unstubbed route
 * cannot 404 into the assertions (#811).
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

const APPLICATION_ID = "app-returning-1";
const STUDENT_ID = "st-returning-1";

const EXISTING_CHILD = {
  student_id: STUDENT_ID,
  full_name: "Ava Kim",
  date_of_birth: "2015-04-02",
  emergency_contact_name: "Jo Kim",
  emergency_contact_phone: "+1 555 0100",
  medical_notes: "Peanut allergy",
  no_medical_conditions: false,
};

const draftApplication = {
  application_id: APPLICATION_ID,
  status: "DRAFT",
  parent_profile: { first_name: "Jo", last_name: "Kim", email: "parent@example.com", phone: "+1 555 0100" },
  child_profile: {
    first_name: "",
    last_name: "",
    date_of_birth: "",
    skill_level: "",
    emergency_contact_name: "",
    emergency_contact_phone: "",
    medical_notes: "",
  },
  selected_session_id: null,
  waiver_accepted: false,
  expires_at: "2027-05-27T00:00:00Z",
};

async function stubOnboarding(
  page: Parameters<typeof stubMe>[0],
  children: unknown[],
): Promise<{ patches: Record<string, unknown>[] }> {
  const patches: Record<string, unknown>[] = [];
  await stubMe(page, {
    user_id: "user-parent-returning",
    email: "parent@example.com",
    academy_id: ACADEMY_A,
    roles: ["parent"],
  });
  await stubMemberships(page, [
    { academy_id: ACADEMY_A, academy_name: "Academy A", role: "parent" },
  ]);
  await stubParentProfile(page, { user_id: "user-parent-returning", children });
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
    return fulfillJson(route, draftApplication);
  });
  await page.route(`**/api/v2/parent/onboarding/${APPLICATION_ID}`, (route) => {
    if (route.request().method() !== "PATCH") return route.fallback();
    const patch = JSON.parse(route.request().postData() ?? "{}");
    patches.push(patch);
    return fulfillJson(route, {
      ...draftApplication,
      parent_profile: { ...draftApplication.parent_profile, ...(patch.parent_profile ?? {}) },
      child_profile: { ...draftApplication.child_profile, ...(patch.child_profile ?? {}) },
    });
  });
  return { patches };
}

test.describe("returning family re-enrolment (#827)", () => {
  test("pre-fills the child step from the pinned student, so no duplicate is authored", async ({
    page,
  }) => {
    const { patches } = await stubOnboarding(page, [EXISTING_CHILD]);

    await page.goto(`/parent/onboarding?child=${STUDENT_ID}`);
    await page.getByTestId("parent-onboarding").getByRole("button", { name: "Next" }).click();

    await expect(page.getByTestId("onboarding-existing-child-picker")).toBeVisible();
    await expect(
      page.getByTestId(`onboarding-existing-child-${STUDENT_ID}`).getByRole("radio"),
    ).toBeChecked();

    // The identity the backend binds on, copied forward verbatim.
    await expect(page.getByLabel("First name")).toHaveValue("Ava");
    await expect(page.getByLabel("Last name")).toHaveValue("Kim");
    await expect(page.getByLabel("Date of birth")).toHaveValue("2015-04-02");
    await expect(page.getByLabel("First name")).toHaveAttribute("readonly", "");

    await page.getByRole("radio", { name: "beginner" }).click();
    await page.getByTestId("parent-onboarding").getByRole("button", { name: "Next" }).click();

    await expect
      .poll(() => patches.filter((p) => p.child_profile).length)
      .toBeGreaterThan(0);
    const saved = patches.filter((p) => p.child_profile).at(-1)?.child_profile as Record<
      string,
      unknown
    >;
    expect(saved.first_name).toBe("Ava");
    expect(saved.last_name).toBe("Kim");
    expect(saved.date_of_birth).toBe("2015-04-02");
  });

  test("a first-time family still gets the plain new-child form", async ({ page }) => {
    await stubOnboarding(page, []);

    await page.goto("/parent/onboarding");
    await page.getByTestId("parent-onboarding").getByRole("button", { name: "Next" }).click();

    await expect(page.getByTestId("onboarding-existing-child-picker")).toHaveCount(0);
    await expect(page.getByLabel("First name")).toHaveValue("");
    await expect(page.getByLabel("First name")).not.toHaveAttribute("readonly", "");
  });
});
