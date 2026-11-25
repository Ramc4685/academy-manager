import { describe, expect, it } from "vitest";

import {
  arrivalFailure,
  checkinActorLine,
  confirmFailureMessage,
  dropoffRefetchInterval,
  parentArrivalView,
} from "./checkin";

const checkin = (state: "none" | "pending" | "confirmed" | "expired", can = false) => ({
  state,
  can_report_arrival: can,
});

describe("parentArrivalView", () => {
  it("hides everything when the academy has check-in off", () => {
    expect(parentArrivalView({ status: "scheduled", checkin: null, can_report_arrival: false })).toBe(
      "hidden",
    );
  });

  it("offers the button only while the server says the window is open", () => {
    expect(
      parentArrivalView({ status: "scheduled", checkin: checkin("none", true), can_report_arrival: true }),
    ).toBe("report");
    expect(
      parentArrivalView({ status: "scheduled", checkin: checkin("none"), can_report_arrival: false }),
    ).toBe("hidden");
  });

  it("shows pending and confirmed from server state", () => {
    expect(parentArrivalView({ status: "scheduled", checkin: checkin("pending") })).toBe("pending");
    expect(parentArrivalView({ status: "scheduled", checkin: checkin("confirmed") })).toBe("confirmed");
  });

  it("says an expired report was not confirmed, and never offers a cancelled class", () => {
    expect(parentArrivalView({ status: "scheduled", checkin: checkin("expired") })).toBe("expired");
    expect(
      parentArrivalView({ status: "cancelled", checkin: checkin("none", true), can_report_arrival: true }),
    ).toBe("hidden");
  });
});

describe("arrivalFailure", () => {
  it("treats a network failure as retryable and says staff were not told", () => {
    const f = arrivalFailure(new TypeError("Failed to fetch"));
    expect(f.retryable).toBe(true);
    expect(f.message).toContain("NOT received");
  });

  it("treats a closed window as final", () => {
    const f = arrivalFailure({
      status: 409,
      code: "Coaching.DropoffWindowClosed",
      details: { reason: "closed" },
    });
    expect(f.retryable).toBe(false);
    expect(f.message).toContain("closed");
    expect(f.message).toContain("NOT received");
  });

  it("explains a window that has not opened yet", () => {
    const f = arrivalFailure({
      status: 409,
      code: "Coaching.DropoffWindowClosed",
      details: { reason: "not_open_yet" },
    });
    expect(f.message).toContain("isn't open yet");
  });

  it("lets a server error be retried", () => {
    expect(arrivalFailure({ status: 500 }).retryable).toBe(true);
    expect(arrivalFailure({ status: 403, code: "Coaching.DropoffCheckinDisabled" }).retryable).toBe(false);
  });
});

describe("checkinActorLine", () => {
  it("names both actors with academy-time clocks", () => {
    expect(
      checkinActorLine(
        {
          reported_at: "2026-11-23T23:42:00Z",
          reported_by_name: "Pat Kim",
          confirmed_at: "2026-11-23T23:50:00Z",
          confirmed_by_name: "Sam Lee",
        },
        "America/Chicago",
      ),
    ).toBe("Reported by Pat Kim at 5:42 PM CST · Confirmed by Sam Lee at 5:50 PM CST");
  });

  it("omits the confirmation while pending and falls back when names are missing", () => {
    expect(checkinActorLine({ reported_at: "2026-11-23T23:42:00Z" }, "America/Chicago")).toBe(
      "Reported by parent at 5:42 PM CST",
    );
  });
});

describe("confirmFailureMessage", () => {
  it("tells staff to correct an Absent or voided mark instead of claiming Checked in", () => {
    const conflict = (existing_status: string) => ({
      status: 409,
      code: "Coaching.ConflictAttendanceExists",
      details: { existing_status },
    });
    expect(confirmFailureMessage(conflict("absent"))).toMatch(/marked Absent.*Correct the mark to Present/);
    expect(confirmFailureMessage(conflict("voided"))).toMatch(/voided.*Correct it to Present/);
    expect(confirmFailureMessage({ status: 409, code: "Coaching.DropoffWindowClosed" })).toBeNull();
  });
});

describe("dropoffRefetchInterval", () => {
  const start = Date.parse("2026-11-23T18:00:00Z");
  const w = { opensAt: "2026-11-23T17:30:00Z", closesAt: "2026-11-23T18:15:00Z" };

  it("refetches exactly when the window opens, then every 30 s while it is open", () => {
    expect(dropoffRefetchInterval([w], start - 32 * 60_000)).toBe(2 * 60_000);
    expect(dropoffRefetchInterval([w], start - 10 * 60_000)).toBe(30_000);
    expect(dropoffRefetchInterval([w], start + 15 * 60_000)).toBe(30_000);
  });

  it("stops once the window has closed, when done, or when nothing is near", () => {
    expect(dropoffRefetchInterval([w], start + 20 * 60_000)).toBe(false);
    expect(dropoffRefetchInterval([{ ...w, done: true }], start)).toBe(false);
    expect(dropoffRefetchInterval([w], start - 24 * 60 * 60_000)).toBe(false);
    expect(dropoffRefetchInterval([{ opensAt: null, closesAt: null }], start)).toBe(false);
  });
});
