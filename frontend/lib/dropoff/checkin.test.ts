import { describe, expect, it } from "vitest";

import { arrivalFailure, checkinActorLine, parentArrivalView } from "./checkin";

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

  it("never shows an expired report or a cancelled class as actionable", () => {
    expect(parentArrivalView({ status: "scheduled", checkin: checkin("expired") })).toBe("hidden");
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
