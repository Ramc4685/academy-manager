import { describe, expect, it } from "vitest";

import type { EnrollmentStatus } from "@/lib/api/admin";

import { rosterActionsFor } from "./RosterPanel";

describe("rosterActionsFor (#696, #711, #714 follow-up)", () => {
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
    expect(rosterActionsFor("active")).toEqual(["pause", "hold", "transfer", "drop", "delete"]);
    expect(rosterActionsFor("paused")).toEqual(["resume", "transfer", "drop", "delete"]);
    expect(rosterActionsFor("held")).toEqual(["return", "transfer", "drop", "delete"]);
    expect(rosterActionsFor("withdrawn")).toEqual(["transfer", "delete"]);
  });

  it("makes Return reachable on a held row and Hold on an active one", () => {
    // #714 listed held rows on the roster but left them with no way back.
    expect(rosterActionsFor("held")).toContain("return");
    expect(rosterActionsFor("active")).toContain("hold");
    // Nothing else gained the pair — a paused row keeps Pause/Resume only.
    expect(rosterActionsFor("paused")).not.toContain("hold");
    expect(rosterActionsFor("paused")).not.toContain("return");
  });
});
