import { beforeEach, describe, expect, it, vi } from "vitest";

import { listAdminUsers } from "./admin";
import * as client from "./client";

describe("listAdminUsers query params (sidebar regroup spec 4.1)", () => {
  beforeEach(() => vi.restoreAllMocks());

  it("sends no query string when nothing is filtered", async () => {
    const spy = vi.spyOn(client, "apiFetch").mockResolvedValue({ users: [] } as never);

    await listAdminUsers();

    expect(spy).toHaveBeenCalledWith("/admin/users", expect.objectContaining({ method: "GET" }));
  });

  it("keeps the legacy single role param", async () => {
    const spy = vi.spyOn(client, "apiFetch").mockResolvedValue({ users: [] } as never);

    await listAdminUsers("coach");

    expect(spy.mock.calls[0]?.[0]).toBe("/admin/users?role=coach");
  });

  it("sends exclude_role and repeats roles= for the union filter", async () => {
    const spy = vi.spyOn(client, "apiFetch").mockResolvedValue({ users: [] } as never);

    await listAdminUsers(undefined, { excludeRole: "parent", roles: ["coach", "assistant_coach"] });

    expect(spy.mock.calls[0]?.[0]).toBe(
      "/admin/users?exclude_role=parent&roles=coach&roles=assistant_coach",
    );
  });

  it("combines role with the new options", async () => {
    const spy = vi.spyOn(client, "apiFetch").mockResolvedValue({ users: [] } as never);

    await listAdminUsers("parent", { excludeRole: "parent" });

    expect(spy.mock.calls[0]?.[0]).toBe("/admin/users?role=parent&exclude_role=parent");
  });
});
