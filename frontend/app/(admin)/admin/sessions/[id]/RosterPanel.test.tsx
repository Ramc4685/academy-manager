import { describe, expect, it } from "vitest";

import type { EnrollmentStatus } from "@/lib/api/admin";

import { partitionRoster, rosterActionsFor, seatsHeldCount } from "./RosterPanel";

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

describe("seatsHeldCount (#734)", () => {
  const row = (status: EnrollmentStatus) => ({ status }) as { status: EnrollmentStatus };

  it("counts held rows as occupying a seat, like SEAT_HOLDING on the backend", () => {
    // A class at capacity 1 whose only row is held is FULL: SeatBroker's
    // try_reserve_seat will refuse the add and claim_longest_held would drop
    // that child. "Open spots 1 / Add 1" invited exactly that.
    expect(seatsHeldCount([row("held")])).toBe(1);
    expect(seatsHeldCount([row("active"), row("held")])).toBe(2);
  });

  it("leaves every seatless status out of the count", () => {
    const seatless: EnrollmentStatus[] = [
      "paused",
      "reclaim_pending",
      "cancelled",
      "deleted",
      "withdrawn",
      "dropped",
    ];
    for (const status of seatless) {
      expect(seatsHeldCount([row(status)]), `seat for ${status}`).toBe(0);
    }
  });
});

describe("partitionRoster (#712, #735)", () => {
  const row = (status: EnrollmentStatus) => ({ status }) as { status: EnrollmentStatus };

  it("keeps held and reclaim_pending on the Active tab, not Past", () => {
    // #712 introduced the Active/Past split; it only tested status === "active",
    // so a held or reclaim_pending row — still live, still actionable via
    // rosterActionsFor (return/transfer/drop) — landed in Past next to
    // genuinely departed students.
    const enrollments = [
      row("active"),
      row("held"),
      row("reclaim_pending"),
      row("withdrawn"),
    ];
    const { active, past } = partitionRoster(enrollments);
    expect(active).toHaveLength(3);
    expect(active.map((e) => e.status)).toEqual(["active", "held", "reclaim_pending"]);
    expect(past).toHaveLength(1);
    expect(past.map((e) => e.status)).toEqual(["withdrawn"]);
  });

  it("sends every terminal status to Past", () => {
    const terminal: EnrollmentStatus[] = ["cancelled", "deleted", "withdrawn", "dropped"];
    for (const status of terminal) {
      const { active, past } = partitionRoster([row(status)]);
      expect(active, `active for ${status}`).toHaveLength(0);
      expect(past, `past for ${status}`).toHaveLength(1);
    }
  });

  it("leaves paused on Past, unchanged from before #735", () => {
    // Only held/reclaim_pending moved; "paused" (seat released, distinct
    // status) keeps its existing Past placement.
    const { active, past } = partitionRoster([row("paused")]);
    expect(active).toHaveLength(0);
    expect(past).toHaveLength(1);
  });
});
