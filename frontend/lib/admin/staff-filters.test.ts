import { describe, expect, it } from "vitest";

import {
  STAFF_ROLE_FILTERS,
  parseRoleParam,
  staffListOptions,
  staffQueryRole,
} from "./staff-filters";

describe("staff filters (sidebar regroup PR 3)", () => {
  it("offers staff pills only, with All staff first and no Parents pill", () => {
    expect(STAFF_ROLE_FILTERS.map((pill) => pill.label)).toEqual([
      "All staff",
      "Coaches",
      "Assistant coaches",
      "Admins",
    ]);
    expect(STAFF_ROLE_FILTERS.map((pill) => pill.value)).not.toContain("parent");
    expect(STAFF_ROLE_FILTERS[0]?.value).toBeUndefined();
  });

  it("asks the BFF to drop parent-only accounts on All staff", () => {
    expect(staffListOptions(undefined)).toEqual({ excludeRole: "parent" });
  });

  it("sends no exclusion once a role pill narrows the list", () => {
    expect(staffListOptions("coach")).toEqual({});
    expect(staffListOptions("admin")).toEqual({});
    // The cached-308 landing still lists parents.
    expect(staffListOptions("parent")).toEqual({});
  });

  it("still accepts role=parent from the URL so the old redirect target works", () => {
    expect(parseRoleParam("parent")).toBe("parent");
    expect(parseRoleParam("coach")).toBe("coach");
    expect(parseRoleParam("owner")).toBeUndefined();
    expect(parseRoleParam(null)).toBeUndefined();
  });

  it("keeps the All staff read off the shared unfiltered users cache key", () => {
    expect(staffQueryRole(undefined)).toBe("staff");
    expect(staffQueryRole(undefined)).not.toBe("all");
    expect(staffQueryRole("coach")).toBe("coach");
  });
});
