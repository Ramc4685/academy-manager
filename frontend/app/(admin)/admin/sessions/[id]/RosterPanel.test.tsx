import { describe, expect, it } from "vitest";

import type { EnrollmentStatus } from "@/lib/api/admin";

import { rosterActionsFor } from "./RosterPanel";

describe("rosterActionsFor (#696, #711)", () => {
  it("offers drop only on the statuses WithdrawEnrollment accepts", () => {
    const expected: Record<EnrollmentStatus, boolean> = {
      active: true,
      paused: true,
      held: true,
      reclaim_pending: false,
      cancelled: false,
      deleted: false,
      withdrawn: false,
      dropped: false,
    };
    for (const [status, offersDrop] of Object.entries(expected)) {
      expect(
        rosterActionsFor(status as EnrollmentStatus).includes("drop"),
        `drop for ${status}`,
      ).toBe(offersDrop);
    }
  });

  it("keeps the pause/resume pair status-specific and delete on every row", () => {
    expect(rosterActionsFor("active")).toEqual(["pause", "transfer", "drop", "delete"]);
    expect(rosterActionsFor("paused")).toEqual(["resume", "transfer", "drop", "delete"]);
    expect(rosterActionsFor("held")).toEqual(["transfer", "drop", "delete"]);
    expect(rosterActionsFor("withdrawn")).toEqual(["transfer", "delete"]);
  });
});
