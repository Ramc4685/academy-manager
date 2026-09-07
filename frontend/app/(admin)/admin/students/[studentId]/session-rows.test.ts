import { describe, expect, it } from "vitest";

import { autopayChip, familyBillingHref, pastEnrollmentRow } from "./session-rows";

describe("autopayChip", () => {
  it("maps billing's autopay axis onto the four admin states", () => {
    expect(autopayChip("active")).toEqual({ variant: "autopayOn", label: "Autopay on" });
    expect(autopayChip("paused")).toEqual({ variant: "paused", label: "Autopay paused" });
    expect(autopayChip("disabled")).toEqual({ variant: "manual", label: "Autopay off" });
  });

  it("treats a missing billing record as no autopay, not as opted out", () => {
    expect(autopayChip(null).label).toBe("No autopay");
    expect(autopayChip(undefined).label).toBe("No autopay");
    expect(autopayChip("").label).toBe("No autopay");
  });

  it("reads every setup_* state as pending", () => {
    expect(autopayChip("setup_started")).toEqual({
      variant: "autopayPend",
      label: "Autopay pending",
    });
    expect(autopayChip("setup_required").label).toBe("Autopay pending");
  });
});

describe("familyBillingHref", () => {
  it("links to the family billing page and encodes the id", () => {
    expect(familyBillingHref("parent-1")).toBe("/admin/families/parent-1");
    expect(familyBillingHref("p/1")).toBe("/admin/families/p%2F1");
  });
  it("is null without a parent", () => {
    expect(familyBillingHref(null)).toBeNull();
    expect(familyBillingHref("")).toBeNull();
  });
});

const base = {
  enrollment_id: "enr-1",
  session_id: "sess-1",
  session_title: "Advanced Footwork",
  location: "Court 1",
  status: "cancelled",
};

function digits(rendered: string) {
  return (rendered.match(/\d+/g) ?? []).map((part) => String(Number(part)));
}

describe("pastEnrollmentRow", () => {
  it("renders a cancelled row with its date, actor and reason", () => {
    const row = pastEnrollmentRow({
      ...base,
      cancelled_at: "2026-08-20T15:00:00Z",
      ended_at: "2026-08-20T15:00:00Z",
      cancelled_by: "parent",
      reason: "Schedule conflict",
    });
    expect(row.statusLabel).toBe("Cancelled");
    expect(row.statusVariant).toBe("expired");
    expect(digits(row.endedOn)).toEqual(expect.arrayContaining(["8", "20", "2026"]));
    expect(row.endedBy).toBe("Parent");
    expect(row.reason).toBe("Schedule conflict");
  });

  it("uses withdrawal_date for a withdrawal and renders it on its stored calendar day", () => {
    // Withdrawal dates are UTC-midnight calendar days (#215): a local render
    // would show 6/30 in US zones.
    const row = pastEnrollmentRow({
      ...base,
      status: "withdrawn",
      withdrawal_date: "2026-07-01T00:00:00Z",
      cancelled_at: "2026-06-01T00:00:00Z",
    });
    expect(row.statusLabel).toBe("Withdrawn");
    expect(digits(row.endedOn)).toEqual(expect.arrayContaining(["7", "1", "2026"]));
  });

  it("falls back to dashes when the lifecycle facts are missing", () => {
    const row = pastEnrollmentRow({ ...base, status: "transferred_out" });
    expect(row.statusLabel).toBe("Transferred");
    expect(row.statusVariant).toBe("transferred");
    expect(row.endedOn).toBe("—");
    expect(row.endedBy).toBe("—");
    expect(row.reason).toBe("—");
  });

  it("keeps an unknown actor verbatim and humanises unknown statuses", () => {
    const row = pastEnrollmentRow({
      ...base,
      status: "some_new_status",
      cancelled_by: "billing-worker",
      reason: "   ",
    });
    expect(row.statusLabel).toBe("some new status");
    expect(row.endedBy).toBe("billing-worker");
    expect(row.reason).toBe("—");
  });
});
