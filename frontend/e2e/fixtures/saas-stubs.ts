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

/**
 * Stub `GET /api/v2/parent/profile`.
 *
 * The parent layout (`app/(parent)/layout.tsx`) fetches this on EVERY parent
 * page to decide whether to show the profile-gap banner (issue #380), so any
 * spec that lands on a `/parent/*` route needs it stubbed — otherwise the
 * request falls through to the dev server with no backend behind it and the
 * browser logs a "Failed to load resource" console error, which trips the
 * `collectConsoleErrors` / `toEqual([])` contract every SaaS spec asserts.
 *
 * Defaults to a complete profile so the banner stays hidden and specs that
 * only care about the page under test are unaffected. Pass `gaps` to render
 * the banner deliberately.
 */
export async function stubParentProfile(
  page: Page,
  overrides: Partial<{
    user_id: string;
    display_name: string;
    email: string;
    email_confirmed: boolean;
    phone: string | null;
    children: unknown[];
    gaps: { parent: string[]; children: Record<string, string[]>; is_complete: boolean };
  }> = {}
): Promise<void> {
  const body = {
    user_id: PARENT_USER.user_id,
    display_name: "Parent Example",
    email: PARENT_USER.email,
    email_confirmed: true,
    phone: "+1 555 0100",
    children: [],
    gaps: { parent: [], children: {}, is_complete: true },
    ...overrides,
  };
  await page.route("**/api/v2/parent/profile", (route) => {
    if (route.request().method() !== "GET") return route.fallback();
    return fulfillJson(route, body);
  });
}

/**
 * The parent layout polls the messages inbox on every /parent/* page (UIM13,
 * issue #450) the same way it fetches the profile. Without this stub the call
 * 404s against the dev server, and every spec that asserts a clean console
 * fails on a page unrelated to what it is testing (issue #465).
 *
 * Defaults to an empty inbox so the unread badge stays hidden.
 */
export async function stubParentMessages(
  page: Page,
  messages: unknown[] = []
): Promise<void> {
  await page.route("**/api/v2/parent/messages", (route) => {
    if (route.request().method() !== "GET") return route.fallback();
    return fulfillJson(route, { messages });
  });
}

export async function stubCoachMessages(
  page: Page,
  messages: unknown[] = []
): Promise<void> {
  await page.route("**/api/v2/coach/messages", (route) => {
    if (route.request().method() !== "GET") return route.fallback();
    return fulfillJson(route, { messages });
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
