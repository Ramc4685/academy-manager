import { afterEach, describe, expect, it, vi } from "vitest";

import * as client from "./client";
import {
  addFamilyContact,
  deleteFamilyContact,
  fetchFamilyContacts,
  updateFamilyContact,
  updateFamilyDetails,
} from "./admin-family-contacts";

afterEach(() => vi.restoreAllMocks());

describe("admin family contacts client", () => {
  it("encodes ids, uses the right verbs and sends no academy", async () => {
    const spy = vi.spyOn(client, "apiFetch").mockResolvedValue({} as never);
    await fetchFamilyContacts("fb/uid");
    expect(spy.mock.calls[0]?.[0]).toBe("/admin/families/fb%2Fuid/contacts");
    await addFamilyContact("p-1", {
      name: "Second Testparent",
      relationship: "parent",
      email: "second@example.test",
      phone: null,
      gets_notices: false,
      gets_invoices: false,
    });
    const body = JSON.parse(String((spy.mock.calls[1]?.[1] as RequestInit).body));
    expect(body).not.toHaveProperty("academy_id");
    expect(body.gets_notices).toBe(false);
    await updateFamilyContact("p-1", "c 1", { gets_notices: true });
    expect(spy.mock.calls[2]?.[0]).toBe("/admin/families/p-1/contacts/c%201");
    expect(spy.mock.calls[2]?.[1]).toMatchObject({ method: "PATCH" });
    await deleteFamilyContact("p-1", "c-1");
    expect(spy.mock.calls[3]?.[1]).toMatchObject({ method: "DELETE" });
    await updateFamilyDetails("p-1", { address: null });
    expect(spy.mock.calls[4]?.[0]).toBe("/admin/families/p-1/details");
    expect(JSON.parse(String((spy.mock.calls[4]?.[1] as RequestInit).body))).toEqual({
      address: null,
    });
  });
});
