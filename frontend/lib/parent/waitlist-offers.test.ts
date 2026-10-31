import { describe, expect, it } from "vitest";

import type { ParentWaitlistEntry } from "@/lib/api/parent";

import {
  classifyOfferError,
  formatCountdown,
  isUrgent,
  msUntil,
  offerFailureMessage,
  offerIsOpen,
  sortWaitlistEntries,
} from "./waitlist-offers";

const MIN = 60_000;
const HOUR = 60 * MIN;
const DAY = 24 * HOUR;
const NOW = Date.parse("2026-09-25T12:00:00Z");

function entry(overrides: Partial<ParentWaitlistEntry>): ParentWaitlistEntry {
  return {
    waitlist_id: "wl-1",
    session_id: "sess-1",
    session_title: "Beginners",
    schedule_label: null,
    location: null,
    student_id: "stu-1",
    student_name: "Asha",
    status: "offered",
    joined_at: "2026-09-01T12:00:00Z",
    offer_expires_at: "2026-09-27T12:00:00Z",
    ...overrides,
  };
}

describe("formatCountdown", () => {
  it.each([
    [2 * DAY + 5 * HOUR + 3 * MIN, "2 days 5 hours left"],
    [DAY, "1 day left"],
    [3 * HOUR + 12 * MIN, "3 hours 12 minutes left"],
    [HOUR, "1 hour left"],
    [8 * MIN + 30_000, "8 minutes left"],
    [30_000, "Less than a minute left"],
    [0, "Offer closed"],
  ])("%d ms -> %s", (ms, text) => {
    expect(formatCountdown(ms)).toBe(text);
  });
});

describe("msUntil / isUrgent", () => {
  it("never goes negative and treats a bad or missing date as closed", () => {
    expect(msUntil("2026-09-25T11:00:00Z", NOW)).toBe(0);
    expect(msUntil(null, NOW)).toBe(0);
    expect(msUntil("not a date", NOW)).toBe(0);
    expect(msUntil("2026-09-25T13:00:00Z", NOW)).toBe(HOUR);
  });

  it("is urgent only inside the last day of an open offer", () => {
    expect(isUrgent(23 * HOUR)).toBe(true);
    expect(isUrgent(DAY + 1)).toBe(false);
    expect(isUrgent(0)).toBe(false);
  });
});

describe("offerIsOpen", () => {
  it("is open only while offered and before the deadline", () => {
    expect(offerIsOpen(entry({}), NOW)).toBe(true);
    // Past the deadline but the hourly sweep has not run yet.
    expect(offerIsOpen(entry({ offer_expires_at: "2026-09-25T11:59:00Z" }), NOW)).toBe(false);
    expect(offerIsOpen(entry({ status: "waiting", offer_expires_at: null }), NOW)).toBe(false);
    expect(offerIsOpen(entry({ status: "expired" }), NOW)).toBe(false);
  });
});

describe("classifyOfferError", () => {
  it.each([
    ["Enrollment.WaitlistOfferExpired", "expired"],
    ["Enrollment.WaitlistOfferNotOpen", "taken"],
    ["Enrollment.WaitlistOfferNotFound", "not_found"],
    ["Enrollment.WaitlistOfferSeatUnavailable", "seat_gone"],
    ["Something.Else", "unknown"],
  ])("%s -> %s", (code, failure) => {
    expect(classifyOfferError(Object.assign(new Error("x"), { status: 409, code }))).toBe(failure);
  });

  it("copes with a plain error or nothing", () => {
    expect(classifyOfferError(new Error("offline"))).toBe("unknown");
    expect(classifyOfferError(null)).toBe("unknown");
  });

  it("tells a family whose seat vanished that they kept their place", () => {
    expect(offerFailureMessage("seat_gone")).toMatch(/still first on the waitlist/);
  });

  it("tells an expired family the seat moved on and whom to ask", () => {
    expect(offerFailureMessage("expired")).toMatch(/next family/);
    expect(offerFailureMessage("expired")).toMatch(/contact the academy/);
  });
});

describe("sortWaitlistEntries", () => {
  it("puts open offers first, soonest deadline first, then waiting, then expired", () => {
    const sorted = sortWaitlistEntries([
      entry({ waitlist_id: "expired", status: "expired" }),
      entry({ waitlist_id: "waiting", status: "waiting", offer_expires_at: null }),
      entry({ waitlist_id: "late", offer_expires_at: "2026-09-28T12:00:00Z" }),
      entry({ waitlist_id: "soon", offer_expires_at: "2026-09-26T12:00:00Z" }),
    ]);
    expect(sorted.map((e) => e.waitlist_id)).toEqual(["soon", "late", "waiting", "expired"]);
  });
});
