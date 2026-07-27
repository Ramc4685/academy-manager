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
 * Stub the `/me/memberships` endpoint. The frontend fetches this as the
 * user lands, so the response shape here must mirror the real BFF
 * contract (`MyMembershipsResponse` in `lib/api/v2/memberships.ts`), not
 * just the fields a given test happens to read.
 */
export async function stubMemberships(
  page: Page,
  memberships: Array<{ academy_id: string; academy_name: string; role: RoleName }>
): Promise<void> {
  const activeAcademyId = memberships[0]?.academy_id ?? "";
  await page.route("**/api/v2/me/memberships", (route) => {
    if (route.request().method() !== "GET") return route.fallback();
    return fulfillJson(route, {
      memberships: memberships.map((m) => ({
        academy_id: m.academy_id,
        academy_name: m.academy_name,
        academy_slug: m.academy_id,
        roles: [m.role],
        status: "active",
        is_default: m.academy_id === activeAcademyId,
      })),
      active_academy_id: activeAcademyId,
    });
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
