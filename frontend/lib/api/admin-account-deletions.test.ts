import { describe, expect, it } from "vitest";

import { deletionForFamily, deletionSummary, type AccountDeletion } from "./admin-account-deletions";

const row = (over: Partial<AccountDeletion> = {}): AccountDeletion => ({
  request_id: "r1",
  user_id: "u1",
  aliases: ["u1", "fb1"],
  display_name: "Pat Parent",
  status: "scheduled",
  requested_at: "2026-11-03T12:00:00Z",
  execute_after: "2026-11-17T12:00:00Z",
  completed_at: null,
  attempts: 0,
  failing_step: null,
  ...over,
});

describe("deletionForFamily", () => {
  it("matches the family by any alias of the parent", () => {
    expect(deletionForFamily([row()], ["fb1"])?.request_id).toBe("r1");
    expect(deletionForFamily([row()], [null, "someone-else"])).toBeUndefined();
    expect(deletionForFamily(undefined, ["u1"])).toBeUndefined();
  });
});

describe("deletionSummary", () => {
  it("tells a pending deletion apart from a finished one", () => {
    expect(deletionSummary(row())).toContain("are removed on");
    expect(deletionSummary(row())).toContain("contact support to restore");
    expect(deletionSummary(row())).toContain("The academy cannot restore it");
    expect(deletionSummary(row({ status: "completed", completed_at: "2026-11-17T13:00:00Z" }))).toContain(
      "were removed on",
    );
  });

  it("stops offering a restore once the removal is under way", () => {
    const text = deletionSummary(row({ status: "running" }));
    expect(text).toContain("being removed now");
    expect(text).not.toContain("restore");
  });

  it("says when the removal keeps failing", () => {
    expect(deletionSummary(row({ attempts: 2 }))).toContain("failed 2 times");
    expect(deletionSummary(row({ attempts: 1 }))).toContain("failed 1 time ");
    // An erasure that failed partway stays non-restorable.
    expect(deletionSummary(row({ attempts: 1 }))).not.toContain("restore");
  });
});
