import {
  devices,
  expect,
  type APIRequestContext,
  type Browser,
  type Page,
} from "@playwright/test";

import { REAL_AUTH_USERS } from "./real-auth-users";

/**
 * Helpers for the real-backend journey spec: real Firebase Auth emulator
 * tokens, the real FastAPI backend behind the Next.js BFF, real MongoDB.
 * Nothing here fakes a response — seeding goes through the same /api/v2
 * routes the admin UI calls, so every write passes the backend's validators.
 */

const EMULATOR_HOST = process.env.FIREBASE_AUTH_EMULATOR_HOST ?? "127.0.0.1:9099";

export type Credentials = { email: string; password: string };

/** Emulator-only ID token for a seeded user (any API key works against the emulator). */
export async function idToken(request: APIRequestContext, user: Credentials): Promise<string> {
  const res = await request.post(
    `http://${EMULATOR_HOST}/identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key=emulator`,
    { data: { email: user.email, password: user.password, returnSecureToken: true } },
  );
  expect(res.ok(), `emulator sign-in for ${user.email}`).toBe(true);
  return (await res.json()).idToken as string;
}

/** Calls the real backend through the frontend BFF proxy and returns the raw response. */
export async function apiRaw(
  request: APIRequestContext,
  token: string,
  method: "GET" | "POST" | "PATCH" | "PUT" | "DELETE",
  path: string,
  data?: unknown,
) {
  return request.fetch(`/api/v2${path}`, {
    method,
    headers: { Authorization: `Bearer ${token}` },
    data,
  });
}

/** Like {@link apiRaw} but fails the test on a non-2xx and returns the JSON body. */
export async function api<T = Record<string, unknown>>(
  request: APIRequestContext,
  token: string,
  method: "GET" | "POST" | "PATCH" | "PUT" | "DELETE",
  path: string,
  data?: unknown,
): Promise<T> {
  const res = await apiRaw(request, token, method, path, data);
  const text = await res.text();
  expect(res.ok(), `${method} ${path} -> ${res.status()} ${text.slice(0, 300)}`).toBe(true);
  return (text ? JSON.parse(text) : {}) as T;
}

export type SeededFamily = {
  studentId: string;
  studentName: string;
  parentId: string;
  parent: Credentials;
};

/**
 * Picks a seeded single-child family by slot so each test owns a different
 * family and the tests stay independent. Seed data is real-shaped, so the
 * parent email is discovered at runtime instead of being hard-coded here.
 */
export async function seededFamily(
  request: APIRequestContext,
  adminToken: string,
  slot: number,
): Promise<SeededFamily> {
  type Row = { student_id: string; full_name: string; parent_id: string; parent_email: string | null };
  const rows: Row[] = [];
  let cursor: string | null = null;
  do {
    const page: { students: Row[]; next_cursor: string | null } = await api(
      request,
      adminToken,
      "GET",
      `/admin/students?limit=100${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ""}`,
    );
    rows.push(...page.students);
    cursor = page.next_cursor;
  } while (cursor);

  const childCount = new Map<string, number>();
  for (const r of rows) childCount.set(r.parent_id, (childCount.get(r.parent_id) ?? 0) + 1);
  const candidates = rows
    .filter((r) => r.parent_email && childCount.get(r.parent_id) === 1)
    .sort((a, b) => a.student_id.localeCompare(b.student_id));
  const pick = candidates[slot];
  expect(pick, `seed has a single-child family for slot ${slot}`).toBeTruthy();
  return {
    studentId: pick.student_id,
    studentName: pick.full_name,
    parentId: pick.parent_id,
    parent: { email: pick.parent_email!, password: REAL_AUTH_USERS.parent.password },
  };
}

/** Academy-local (America/Chicago, the seeded BLno timezone) calendar date. */
export function academyToday(): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone: "America/Chicago" }).format(new Date());
}

/** "YYYY-MM" for the academy-local month, shifted by `offset` months. */
export function academyMonth(offset = 0): string {
  const [y, m] = academyToday().split("-").map(Number);
  const d = new Date(Date.UTC(y, m - 1 + offset, 1));
  return `${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, "0")}`;
}

export type CreatedClass = { sessionId: string; title: string; coachId: string };

/**
 * Creates a priced class that meets every day at 00:00 academy time, so
 * today's occurrence has always started (the coach can mark it) whatever
 * hour CI runs. Coach is the seeded coach that owns an existing class.
 */
export async function createDailyClass(
  request: APIRequestContext,
  adminToken: string,
  coachId: string,
  label: string,
  amountCents: number,
): Promise<CreatedClass> {
  const title = `E2E ${label} ${Date.now().toString(36)}`;
  const session: { session_id: string } = await api(request, adminToken, "POST", "/admin/sessions", {
    coach_id: coachId,
    title,
    // The duplicate-series guard keys on coach + location + day + time.
    location: `Court ${title}`,
    capacity: 5,
    amount_cents: amountCents,
    days_of_week: ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
    start_time: "00:00",
    end_time: "00:30",
    timezone: "America/Chicago",
  });
  return { sessionId: session.session_id, title, coachId };
}

/** user_id of the seeded coach (by email), read from the admin sessions list. */
export async function seededCoachId(
  request: APIRequestContext,
  adminToken: string,
  coachName: string,
): Promise<string> {
  const { sessions }: { sessions: { coach_id: string; coach_name: string | null }[] } = await api(
    request,
    adminToken,
    "GET",
    "/admin/sessions",
  );
  const match = sessions.find((s) => s.coach_name === coachName);
  expect(match, `seeded class coached by ${coachName}`).toBeTruthy();
  return match!.coach_id;
}

export async function enroll(
  request: APIRequestContext,
  adminToken: string,
  sessionId: string,
  family: SeededFamily,
): Promise<string> {
  const row: { enrollment_id: string } = await api(request, adminToken, "POST", "/admin/enrollments", {
    session_id: sessionId,
    student_id: family.studentId,
    parent_id: family.parentId,
    full_name: family.studentName,
  });
  return row.enrollment_id;
}

export type DraftInvoice = { invoice_id: string; total_cents: number; status: string; period: string };

/** The admin's per-enrollment monthly invoice ("Bill this month"), then sent so the parent sees it. */
export async function billAndSend(
  request: APIRequestContext,
  adminToken: string,
  enrollmentId: string,
  period: string,
): Promise<DraftInvoice> {
  const invoice: DraftInvoice = await api(
    request,
    adminToken,
    "POST",
    `/admin/enrollments/${enrollmentId}/invoices/bill-period`,
    { period },
  );
  await api(request, adminToken, "POST", `/admin/billing/invoices/${invoice.invoice_id}/send`, {});
  return invoice;
}

/** "$43.21" — how the app renders cents. */
export function usd(cents: number): string {
  return `$${(cents / 100).toFixed(2)}`;
}

/**
 * A fresh, isolated browser context per persona (Firebase keeps its session
 * in per-origin storage), signed in through the real login form.
 */
export async function signedInPage(
  browser: Browser,
  baseURL: string,
  user: Credentials,
  landing: RegExp,
): Promise<Page> {
  const context = await browser.newContext({ ...devices["Pixel 7"], baseURL });
  const page = await context.newPage();
  await page.goto("/login", { waitUntil: "domcontentloaded", timeout: 90_000 });
  await expect(page.getByTestId("login-submit")).toBeEnabled({ timeout: 90_000 });
  await page.getByLabel("Email").fill(user.email);
  await page.getByLabel("Password").fill(user.password);
  await page.getByTestId("login-submit").click();
  await expect(page).toHaveURL(landing, { timeout: 60_000 });
  return page;
}
