import { afterAll, beforeAll, describe, expect, it } from "vitest";

import { DEPARTURE_ACTION_DESCRIPTION } from "@/components/admin/enrollment/departure-actions.logic";
import {
  autopayChip,
  enrolledSessionActions,
  familyBillingHref,
  pastEnrollmentRow,
  sessionRosterHref,
} from "./session-rows";

describe("autopayChip", () => {
  it("uses the family billing page's wording for on / paused / off", () => {
    expect(autopayChip("active")).toEqual({ variant: "autopayOn", label: "Autopay" });
    expect(autopayChip("paused")).toEqual({ variant: "manual", label: "Autopay off" });
    expect(autopayChip("disabled")).toEqual({ variant: "manual", label: "Manual" });
  });

  it("reads the default not_offered and a merely offered setup as Manual, not pending", () => {
    // `not_offered` is the repository default for every billing enrollment;
    // labelling it "pending" would suggest a card setup that never started.
    expect(autopayChip("not_offered")).toEqual({ variant: "manual", label: "Manual" });
    expect(autopayChip("offered")).toEqual({ variant: "manual", label: "Manual" });
  });

  it("treats a missing billing record as Manual, like the family page", () => {
    expect(autopayChip(null).label).toBe("Manual");
    expect(autopayChip(undefined).label).toBe("Manual");
    expect(autopayChip("").label).toBe("Manual");
  });

  it("reserves pending for a card setup that has actually started", () => {
    expect(autopayChip("setup_started")).toEqual({
      variant: "autopayPend",
      label: "Autopay pending",
    });
    expect(autopayChip("some_future_state").label).toBe("Manual");
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
  // Pin the process to a US zone so a UTC-midnight day would render a day
  // early if it were formatted as a local instant. Node re-reads TZ on the
  // next Date call, so setting it here is enough; restore it afterwards.
  const originalTz = process.env.TZ;
  beforeAll(() => {
    process.env.TZ = "America/Chicago";
  });
  afterAll(() => {
    if (originalTz === undefined) delete process.env.TZ;
    else process.env.TZ = originalTz;
  });

  it("renders an admin cancel stored at UTC midnight on its stored calendar day", () => {
    // Admin cancel stamps cancelled_at = _start_of_day_utc(effective_date);
    // a local render in Chicago would show 8/31.
    const row = pastEnrollmentRow({
      ...base,
      cancelled_at: "2026-09-01T00:00:00Z",
      ended_at: "2026-09-01T00:00:00Z",
      cancelled_by: "admin",
      reason: "Moved away",
    });
    expect(new Date("2026-09-01T00:00:00Z").getDate()).toBe(31); // TZ pin is in effect
    expect(digits(row.endedOn)).toEqual(expect.arrayContaining(["9", "1", "2026"]));
    expect(digits(row.endedOn)).not.toContain("31");
    expect(row.endedBy).toBe("Admin");
    expect(row.reason).toBe("Moved away");
  });

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
    // Pre-#651 cancelled rows carry no date, actor or reason at all.
    const row = pastEnrollmentRow({ ...base });
    expect(row.statusLabel).toBe("Cancelled");
    expect(row.statusVariant).toBe("expired");
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

describe("re-enrolling a past row (#827)", () => {
  it("carries the class the student left, so Past is no longer a dead end", () => {
    const row = pastEnrollmentRow({ ...base, cancelled_at: "2026-09-01T00:00:00Z" });
    expect(row.sessionId).toBe("sess-1");
    expect(sessionRosterHref(row.sessionId)).toBe("/admin/sessions/sess-1");
  });

  it("encodes an id that would otherwise break the path", () => {
    expect(sessionRosterHref("sess/1")).toBe("/admin/sessions/sess%2F1");
  });
});

/**
 * Issue #865: the Sessions tab was the last admin list still rendering a bare
 * `<table>` at every width, so on a phone Fee, Discount, Hold and Transfer sat
 * off-screen behind a sideways scroll. The phone row puts them in one 44px
 * menu — and it must offer exactly what the desktop row offers, so the two
 * layouts cannot disagree about what can be done to an enrollment.
 */
describe("enrolledSessionActions (#865)", () => {
  const active = { status: "active", discount: null };

  it("offers Hold, Transfer, Fee and Discount on an active enrollment", () => {
    expect(enrolledSessionActions(active).map((a) => a.label)).toEqual([
      "Hold",
      "Transfer",
      "Fee",
      "Discount",
    ]);
  });

  it("swaps Hold for Return once the enrollment is held, exactly like the roster", () => {
    expect(
      enrolledSessionActions({ status: "held", discount: null }).map((a) => a.key),
    ).toEqual(["return", "transfer", "fee", "discount"]);
  });

  it("a status with no hold pair still gets Transfer, Fee and Discount", () => {
    expect(
      enrolledSessionActions({ status: "paused", discount: null }).map((a) => a.key),
    ).toEqual(["transfer", "fee", "discount"]);
  });

  it("says Edit discount once one is attached, matching the table's button", () => {
    const labels = enrolledSessionActions({
      status: "active",
      discount: { label: "Scholarship" },
    }).map((a) => a.label);
    expect(labels).toContain("Edit discount");
    expect(labels).not.toContain("Discount");
  });

  it("carries the shared seat/billing/family wording for the departure actions", () => {
    const hold = enrolledSessionActions(active).find((a) => a.key === "hold");
    expect(hold?.description).toBe(DEPARTURE_ACTION_DESCRIPTION.hold);
  });
});
