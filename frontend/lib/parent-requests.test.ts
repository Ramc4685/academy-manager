import { describe, expect, it } from "vitest";

import { assignedClassCopy, requestStatusChipVariant } from "./parent-requests";

describe("requestStatusChipVariant", () => {
  it("maps each known backend status to its Chip variant", () => {
    expect(requestStatusChipVariant("pending")).toBe("pending");
    expect(requestStatusChipVariant("approved")).toBe("approved");
    expect(requestStatusChipVariant("denied")).toBe("denied");
    expect(requestStatusChipVariant("expired")).toBe("expired");
    expect(requestStatusChipVariant("converted")).toBe("converted");
  });

  it("falls back to pending for an unrecognized status", () => {
    expect(requestStatusChipVariant("some_future_status")).toBe("pending");
  });
});

describe("assignedClassCopy (#1038)", () => {
  const assigned = {
    occurrence_id: "occ-b1",
    session_id: "sess-b",
    session_title: "Squad B",
    location: "Court 7",
    start_at: "2026-10-03T22:00:00Z",
    end_at: "2026-10-03T23:00:00Z",
    timezone: "America/Chicago",
    status: "scheduled",
  };

  it("renders class, academy-local time with zone label, and venue", () => {
    expect(assignedClassCopy(assigned, null)).toEqual({
      title: "Squad B",
      when: "Sat, Oct 3 · 5:00 PM – 6:00 PM CDT",
      where: "Court 7",
      cancelled: false,
    });
  });

  it("uses the class's academy timezone over the page fallback", () => {
    const copy = assignedClassCopy({ ...assigned, timezone: "Europe/London" }, "America/Chicago");
    expect(copy?.when).toBe("Sat, Oct 3 · 11:00 PM – 12:00 AM GMT+1");
  });

  it("flags a cancelled class and a missing venue", () => {
    const copy = assignedClassCopy({ ...assigned, status: "cancelled", location: null }, null);
    expect(copy?.cancelled).toBe(true);
    expect(copy?.where).toBe("Venue to be confirmed");
  });

  it("returns null when nothing is assigned", () => {
    expect(assignedClassCopy(null, "America/Chicago")).toBeNull();
    expect(assignedClassCopy(undefined, "America/Chicago")).toBeNull();
  });
});
