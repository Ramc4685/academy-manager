/**
 * #895: a failed mark can be RETRIED from the Needs-review tray.
 *
 * Before this, the tray offered only "Dismiss" — a coach whose mark bounced on
 * a transient domain error had to find the session again and re-mark by hand,
 * and the tray's whole point is that they may well have left it. Retry
 * re-enqueues the SAME record: same `mutation_id` (which is also the server's
 * idempotency key) and the same payload, flipped back to `queued` and handed to
 * the existing sync loop. Nothing about the offline queue contract, the
 * attendance save path or the payload changes.
 *
 * The tray is IndexedDB-backed with no server read, so the spec seeds one
 * `needs_review` record directly into `academy-offline` → `mutations`
 * (lib/offline/idb.ts: DB_NAME "academy-offline", DB_VERSION 1, keyPath
 * "mutation_id") and reloads. That keeps it independent of the Wave-1B
 * offline-writes flag, which still gates coach-offline-writes.spec.ts.
 */

import { test, expect } from "../fixtures/mock-api";

const MUTATION_ID = "01J0000000000000000000RTRY";

const SEEDED = {
  mutation_id: MUTATION_ID,
  endpoint: "/coach/attendance",
  payload: {
    mutation_id: MUTATION_ID,
    occurrence_id: "s-today-1",
    session_id: "s-today-1",
    student_id: "st1",
    status: "present",
    marked_at_client: "2026-09-21T09:00:00.000Z",
    client_app_version: "v2-w1b",
  },
  labels: { student_full_name: "Alice Adams", session_title: "Junior A" },
  status: "needs_review",
  attempts: 3,
  created_at: "2026-09-21T09:00:00.000Z",
  last_attempt_at: "2026-09-21T09:00:05.000Z",
  error: {
    code: "Coaching.ConflictAttendanceExists",
    message: "attendance already recorded",
  },
};

async function seedTray(
  page: import("@playwright/test").Page,
  record: Record<string, unknown>,
): Promise<void> {
  await page.evaluate(async (row) => {
    await new Promise<void>((resolve, reject) => {
      const req = indexedDB.open("academy-offline", 1);
      req.onupgradeneeded = () => {
        const db = req.result;
        if (!db.objectStoreNames.contains("mutations")) {
          const store = db.createObjectStore("mutations", {
            keyPath: "mutation_id",
          });
          store.createIndex("created_at", "created_at", { unique: false });
        }
        if (!db.objectStoreNames.contains("audit")) {
          const store = db.createObjectStore("audit", {
            keyPath: "id",
            autoIncrement: true,
          });
          store.createIndex("ts", "ts", { unique: false });
        }
      };
      req.onsuccess = () => {
        const db = req.result;
        const tx = db.transaction("mutations", "readwrite");
        tx.objectStore("mutations").put(row);
        tx.oncomplete = () => resolve();
        tx.onerror = () => reject(tx.error);
      };
      req.onerror = () => reject(req.error);
    });
  }, record);
}

test.describe("Coach needs-review retry (#895)", () => {
  test("Retry re-sends the failed mark under its original idempotency key", async ({
    page,
    mock,
  }) => {
    await page.goto("/coach/needs-review");
    await expect(page.getByTestId("needs-review")).toBeVisible();
    await seedTray(page, SEEDED);
    await page.reload();

    const row = page.getByTestId(`tray-${MUTATION_ID}`);
    await expect(row).toContainText("Alice Adams");

    // The action id deliberately does NOT extend the row id, so a prefix
    // match for rows never picks up an action (see e2e/helpers/row-actions.ts).
    const retry = page.getByTestId(`tray-retry-${MUTATION_ID}`);
    await expect(retry).toBeVisible();
    await expect(
      row.getByRole("button", { name: "Dismiss", exact: true }),
    ).toBeVisible();

    await retry.click();

    await expect.poll(() => mock.attendanceCalls.length).toBe(1);
    expect(mock.attendanceCalls[0]).toMatchObject({
      mutation_id: MUTATION_ID,
      occurrence_id: "s-today-1",
      student_id: "st1",
      status: "present",
    });

    // Sync succeeded → the queue dropped the record and the tray empties
    // without a manual reload.
    await expect(page.getByTestId("tray-empty")).toBeVisible();
    await expect(page.getByTestId(`tray-${MUTATION_ID}`)).toHaveCount(0);
  });

  test("a Retry that fails again leaves the mark in the tray", async ({
    page,
    mock,
  }) => {
    mock.attendanceResponder = () => ({
      status: 409,
      body: {
        error: {
          code: "Coaching.SessionCancelled",
          message: "session was cancelled",
          details: {},
        },
      },
    });

    await page.goto("/coach/needs-review");
    await expect(page.getByTestId("needs-review")).toBeVisible();
    await seedTray(page, SEEDED);
    await page.reload();

    await expect(page.getByTestId(`tray-retry-${MUTATION_ID}`)).toBeVisible();
    await page.getByTestId(`tray-retry-${MUTATION_ID}`).click();

    await expect.poll(() => mock.attendanceCalls.length).toBe(1);
    // Still there, with the new reason — and retryable again.
    const row = page.getByTestId(`tray-${MUTATION_ID}`);
    await expect(row).toContainText("This session was cancelled");
    await expect(page.getByTestId(`tray-retry-${MUTATION_ID}`)).toBeVisible();
  });
});
