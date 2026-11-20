import { describe, expect, it } from "vitest";

import {
  assignedClassCopy,
  makeupCandidateKey,
  makeupCandidateLabel,
  requestStatusChipVariant,
} from "./parent-requests";

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

describe("makeup candidate picker (#1037)", () => {
  const base = {
    occurrence_id: "occ-1",
    session_id: "sess-1",
    class_title: "Tuesday Beginners",
    // 00:30 UTC Wednesday is still Tuesday evening in Chicago.
    start_at: "2026-11-18T00:30:00Z",
    end_at: "2026-11-18T01:30:00Z",
    has_notice: false,
    expires_at: "2026-12-02T00:00:00Z",
  };
  const ana = { ...base, student_id: "s-ana", student_name: "Ana Fake" };
  const ben = { ...base, student_id: "s-ben", student_name: "Ben Fake" };

  it("keys siblings in the same class apart", () => {
    expect(makeupCandidateKey(ana)).not.toBe(makeupCandidateKey(ben));
    expect(makeupCandidateKey(ana)).toBe("s-ana:occ-1");
  });

  it("labels child, class and the academy-local date and time", () => {
    expect(makeupCandidateLabel(ana, "America/Chicago")).toBe(
      "Ana Fake — Tuesday Beginners — Tue, Nov 17 · 6:30 PM – 7:30 PM CST",
    );
  });
});
