import { afterEach, describe, expect, it, vi } from "vitest";

import * as client from "./client";
import {
  addFamilyFollowUp,
  deleteFamilyNote,
  fetchFollowUpQueue,
  updateFamilyFollowUp,
} from "./admin-family-crm";

afterEach(() => vi.restoreAllMocks());

describe("admin family CRM client", () => {
  it("builds the queue query", async () => {
    const spy = vi.spyOn(client, "apiFetch").mockResolvedValue({} as never);
    await fetchFollowUpQueue("me");
    await fetchFollowUpQueue("all", "overdue");
    expect(spy.mock.calls[0]?.[0]).toBe("/admin/follow-ups?assignee=me");
    expect(spy.mock.calls[1]?.[0]).toBe("/admin/follow-ups?assignee=all&bucket=overdue");
  });

  it("encodes family and record ids and sends no academy", async () => {
    const spy = vi.spyOn(client, "apiFetch").mockResolvedValue({} as never);
    await deleteFamilyNote("fb/uid", "n 1");
    expect(spy.mock.calls[0]?.[0]).toBe("/admin/families/fb%2Fuid/notes/n%201");
    expect(spy.mock.calls[0]?.[1]).toMatchObject({ method: "DELETE" });
    await addFamilyFollowUp("p-1", { title: "Call", due_on: "2026-09-30", assignee_user_id: "u" });
    const body = JSON.parse(String((spy.mock.calls[1]?.[1] as RequestInit).body));
    expect(body).toEqual({ title: "Call", due_on: "2026-09-30", assignee_user_id: "u" });
    await updateFamilyFollowUp("p-1", "f-1", { status: "done" });
    expect(spy.mock.calls[2]?.[0]).toBe("/admin/families/p-1/follow-ups/f-1");
    expect(spy.mock.calls[2]?.[1]).toMatchObject({ method: "PATCH" });
  });
});
