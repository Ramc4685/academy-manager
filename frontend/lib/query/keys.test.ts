import { describe, expect, it } from "vitest";

import { queryKeys } from "./keys";

describe("queryKeys.admin.overdueFamilies", () => {
  it("sits under collectionsAll so payment invalidations refresh it", () => {
    const prefix = queryKeys.admin.collectionsAll();
    expect(queryKeys.admin.overdueFamilies().slice(0, prefix.length)).toEqual([...prefix]);
  });
});
