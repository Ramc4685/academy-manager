/**
 * Wave 5 — SaaS v2 mock helpers shared by saas-*.spec.ts files.
 *
 * Spec authors compose `stubMe`, `stubMembershipSwitch`, etc., with their
 * own per-test route handlers. Every helper here stubs ONLY /api/v2/*
 * paths so the tenant-isolation guard never trips on these.
 */

import type { Page, Route } from "@playwright/test";

export type RoleName = "admin" | "coach" | "parent";

export interface MockUser {
  user_id: string;
  email: string;
  academy_id: string;
  roles: RoleName[];
}

export const ACADEMY_A = "academy-aces";
export const ACADEMY_B = "academy-rally";

export const ADMIN_USER_A: MockUser = {
  user_id: "user-admin-w5",
  email: "admin@example.com",
  academy_id: ACADEMY_A,
  roles: ["admin"],
};

export const COACH_USER_B: MockUser = {
  user_id: "user-coach-b",
  email: "coach@example.com",
  academy_id: ACADEMY_B,
  roles: ["coach"],
};

export const PARENT_USER: MockUser = {
  user_id: "user-parent-w5",
  email: "parent@example.com",
  academy_id: ACADEMY_A,
  roles: ["parent"],
};

export function fulfillJson(
  route: Route,
  body: unknown,
  status = 200
): Promise<void> {
  return route.fulfill({
    status,
    contentType: "application/json",
    body: JSON.stringify(body),
  });
}

export async function stubMe(page: Page, user: MockUser): Promise<void> {
  await page.route("**/api/v2/me", (route) => {
    if (route.request().method() !== "GET") return route.fallback();
    return fulfillJson(route, user);
  });
}

/**
 * Stub multi-membership endpoint. The frontend may issue this as the
 * user lands. We treat the response as the source of truth for which
 * academies the user can switch into.
 */
export async function stubMemberships(
  page: Page,
  memberships: Array<{ academy_id: string; academy_name: string; role: RoleName }>
): Promise<void> {
  await page.route("**/api/v2/me/memberships", (route) => {
    if (route.request().method() !== "GET") return route.fallback();
    return fulfillJson(route, { memberships });
  });
}

export async function stubAcademy(page: Page, academyId: string): Promise<void> {
  await page.route(/\/api\/v2\/admin\/academy(?:\?.*)?$/, (route) => {
    if (route.request().method() !== "GET") return route.fallback();
    return fulfillJson(route, {
      academy_id: academyId,
      display_name: academyId === ACADEMY_A ? "Aces Academy" : "Rally Academy",
      timezone: "UTC",
      contact_email: null,
      contact_phone: null,
      hours_text: null,
      address: null,
    });
  });
}
