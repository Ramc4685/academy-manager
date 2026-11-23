import { describe, expect, it } from "vitest";

import {
  absenceMakeupDisplay,
  assignedClassCopy,
  makeupCandidateKey,
  makeupBookingHref,
  makeupCandidateLabel,
  makeupEmptyMessage,
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

describe("makeupEmptyMessage (#1041)", () => {
  it("says makeups are off rather than that nothing was missed", () => {
    expect(makeupEmptyMessage({ makeups_enabled: false, requires_notice: false })).toMatch(/turned off/);
  });

  it("explains the on-time notice rule when the academy requires it", () => {
    expect(makeupEmptyMessage({ makeups_enabled: true, requires_notice: true })).toMatch(
      /on-time absence notice/,
    );
    expect(makeupEmptyMessage({ makeups_enabled: true, requires_notice: false })).not.toMatch(/notice/);
  });
});

describe("absenceMakeupDisplay", () => {
  const ids = { studentId: "kid-1", occurrenceId: "occ:2026-11-14" };
  const tz = "America/Chicago";

  it("shows Reported, with the server's reason when a past class can't be made up", () => {
    expect(absenceMakeupDisplay({ state: "reported" }, ids, tz)).toEqual({
      label: "Reported",
      chip: "approved",
      detail: null,
      bookHref: null,
    });
    expect(
      absenceMakeupDisplay({ state: "reported", reason: "Marked present for this class." }, ids, tz)
        .detail,
    ).toBe("Marked present for this class.");
  });

  it("links an eligible makeup straight to booking with the class pre-selected", () => {
    const display = absenceMakeupDisplay(
      { state: "eligible", expires_at: "2026-12-14T15:00:00Z" },
      ids,
      tz,
    );
    expect(display.label).toBe("Makeup eligible");
    expect(display.detail).toMatch(/^Request a makeup by .*Dec 14/);
    expect(display.bookHref).toBe(makeupBookingHref("kid-1", "occ:2026-11-14"));
    expect(display.bookHref).toBe("/parent/requests?tab=makeups&makeup=kid-1%3Aocc%3A2026-11-14");
  });

  it("names the booked makeup class and date", () => {
    const display = absenceMakeupDisplay(
      {
        state: "booked",
        booked_class: {
          occurrence_id: "occ-t",
          session_id: "s",
          session_title: "Saturday Juniors",
          location: null,
          start_at: "2026-11-21T15:00:00Z",
          end_at: "2026-11-21T16:00:00Z",
          timezone: tz,
          status: "scheduled",
        },
      },
      ids,
      tz,
    );
    expect(display.label).toBe("Makeup booked");
    expect(display.chip).toBe("makeup");
    expect(display.detail).toBe("Saturday Juniors — Sat, Nov 21 · 9:00 AM – 10:00 AM CST");
    expect(display.bookHref).toBeNull();
  });

  it("shows requested and expired without a booking link", () => {
    expect(absenceMakeupDisplay({ state: "requested" }, ids, tz)).toMatchObject({
      label: "Makeup requested",
      bookHref: null,
    });
    expect(absenceMakeupDisplay({ state: "expired" }, ids, tz)).toMatchObject({
      label: "Makeup expired",
      chip: "expired",
      bookHref: null,
    });
  });
});
