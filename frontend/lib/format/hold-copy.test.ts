import { describe, expect, it } from "vitest";

import { holdReturnLabel, holdScheduleNote, isHeldEnrollment, partitionByHold } from "./hold-copy";

describe("isHeldEnrollment", () => {
  it("recognises the held status", () => {
    expect(isHeldEnrollment({ status: "held" })).toBe(true);
  });

  it("leaves every other status alone", () => {
    expect(isHeldEnrollment({ status: "active" })).toBe(false);
    expect(isHeldEnrollment({ status: "paused" })).toBe(false);
  });
});

describe("partitionByHold", () => {
  it("keeps held rows instead of dropping them with the inactive ones", () => {
    const rows = [
      { enrollment_id: "a", status: "active" },
      { enrollment_id: "h", status: "held" },
      { enrollment_id: "w", status: "withdrawn" },
    ];

    const { active, held } = partitionByHold(rows);

    expect(active.map((r) => r.enrollment_id)).toEqual(["a"]);
    expect(held.map((r) => r.enrollment_id)).toEqual(["h"]);
  });
});

describe("holdReturnLabel", () => {
  it("names the return date the admin promised", () => {
    // A calendar date, not an instant: it must render as the same day in
    // every viewer timezone (a UTC-midnight parse would read Oct 14 in
    // Chicago).
    expect(holdReturnLabel("2026-10-15")).toBe("On hold until Oct 15, 2026");
  });

  it("falls back to a bare label when the date is missing", () => {
    expect(holdReturnLabel(null)).toBe("On hold");
    expect(holdReturnLabel("not-a-date")).toBe("On hold");
  });
});

describe("holdScheduleNote", () => {
  it("explains an empty schedule when a class is on hold", () => {
    expect(
      holdScheduleNote([
        { status: "held", session_title: "Evening Squad", hold_return_on: "2026-10-15" },
      ]),
    ).toBe("Evening Squad is on hold — classes resume Oct 15, 2026.");
  });

  it("says nothing when nothing is on hold", () => {
    expect(holdScheduleNote([{ status: "active" }])).toBeNull();
  });
});

describe("partitionByHold does not drop live rows", () => {
  it("keeps a paused enrollment instead of losing it", () => {
    // Issue #773: the parent portal rendered [...active, ...held], so a
    // paused class vanished from the child's card with no explanation —
    // the same shape of bug #740 fixed for held rows.
    const rows = [
      { status: "active" },
      { status: "held" },
      { status: "paused" },
    ];
    const { active, held, other } = partitionByHold(rows);
    expect(active).toEqual([{ status: "active" }]);
    expect(held).toEqual([{ status: "held" }]);
    expect(other).toEqual([{ status: "paused" }]);
    expect([...active, ...held, ...other]).toHaveLength(rows.length);
  });

  it("carries an unfamiliar status through rather than swallowing it", () => {
    const { other } = partitionByHold([{ status: "reclaim_pending" }]);
    expect(other).toEqual([{ status: "reclaim_pending" }]);
  });
});
