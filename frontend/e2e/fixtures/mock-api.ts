/**
 * Playwright fixture: mock the v2 BFF + Firebase auth.
 *
 * For Wave 1A E2E we don't spin a real backend — we stub network at the
 * Playwright route layer. Real backend tests live in
 * `backend/v2/tests/interface/` (with FastAPI TestClient) and the
 * production cutover canary (W1A-20) is the integration gate.
 */

import { test as base, type Page, type Route } from "@playwright/test";

export interface MockState {
  today: {
    date: string;
    sessions: Array<{
      session_id: string;
      occurrence_id: string;
      title: string;
      location: string;
      start_at: string;
      end_at: string;
      roster: Array<{
        student_id: string;
        full_name: string;
        enrollment_status: "active" | "paused" | "cancelled";
      }>;
    }>;
  };
  attendanceCalls: Array<Record<string, unknown>>;
  attendanceResponder?: (body: Record<string, unknown>) => {
    status: number;
    body: Record<string, unknown>;
  };
}

export const test = base.extend<{
  mock: MockState;
  signIn: () => Promise<void>;
}>({
  mock: async ({ page }, use) => {
    const state: MockState = {
      today: {
        date: new Date().toISOString().slice(0, 10),
        sessions: [
          {
            session_id: "s-today-1",
            occurrence_id: "occ-today-1",
            title: "Junior A",
            location: "Court 1",
            start_at: `${new Date().toISOString().slice(0, 10)}T09:00:00Z`,
            end_at: `${new Date().toISOString().slice(0, 10)}T10:30:00Z`,
            roster: [
              {
                student_id: "st1",
                full_name: "Alice",
                enrollment_status: "active",
              },
              {
                student_id: "st2",
                full_name: "Bob",
                enrollment_status: "active",
              },
            ],
          },
        ],
      },
      attendanceCalls: [],
    };

    await page.route("**/api/v2/me", async (route: Route) => {
      if (route.request().method() !== "GET") return route.fallback();
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          user_id: "user-coach-e2e",
          email: "coach@example.com",
          academy_id: "academy-e2e",
          roles: ["coach"],
        }),
      });
    });

    await page.route("**/api/v2/coach/today*", async (route: Route) => {
      if (route.request().method() !== "GET") return route.fallback();
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(state.today),
      });
    });

    await page.route("**/api/v2/coach/attendance", async (route: Route) => {
      if (route.request().method() !== "POST") return route.fallback();
      const body = JSON.parse(route.request().postData() ?? "{}");
      state.attendanceCalls.push(body);
      const responder = state.attendanceResponder?.(body);
      if (responder) {
        return route.fulfill({
          status: responder.status,
          contentType: "application/json",
          body: JSON.stringify(responder.body),
        });
      }
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          attendance_id: body.mutation_id,
          occurrence_id: body.occurrence_id,
          session_id: body.session_id,
          student_id: body.student_id,
          status: body.status,
          marked_at: new Date().toISOString(),
        }),
      });
    });

    await page.route(
      "**/api/v2/coach/sessions/*/lesson-plans",
      async (route: Route) => {
        if (route.request().method() !== "GET") return route.fallback();
        return route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({ plans: [] }),
        });
      },
    );

    await page.route(
      "**/api/v2/coach/sessions/*/progress-notes",
      async (route: Route) => {
        if (route.request().method() !== "GET") return route.fallback();
        return route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({ notes: [] }),
        });
      },
    );

    await use(state);
  },

  signIn: async ({ page }, use) => {
    await use(async () => {
      await page.addInitScript(() => {
        // Mock Firebase user before the page boots.
        (window as unknown as { __FAKE_AUTH__: boolean }).__FAKE_AUTH__ = true;
      });
    });
  },
});

export { expect } from "@playwright/test";

export async function bypassAuth(page: Page): Promise<void> {
  // For pages that gate on Firebase, we navigate directly to coach surfaces
  // with the auth state pre-seeded. The coach layout reads onAuthChange
  // synchronously — in tests we override the module via init script.
  await page.addInitScript(() => {
    const FAKE_USER = {
      uid: "coach-1",
      email: "coach@example.com",
      getIdToken: async () => "fake-id-token",
    };
    // Patch the Firebase auth module's named exports for client bundles
    // that imported them. The Wave-1A login flow uses `onAuthChange` which
    // we stub to immediately fire the callback.
    Object.defineProperty(window, "__fakeFirebaseUser", { value: FAKE_USER });
  });
}
