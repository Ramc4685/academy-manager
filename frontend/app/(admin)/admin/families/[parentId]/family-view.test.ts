import { describe, expect, it } from "vitest";

import {
  autopayToggle,
  currentPeriod,
  defaultDueDate,
  enrollmentBillPeriodPriceCents,
  enrollmentOptions,
  enrollmentPriceCents,
  invoiceActionLabel,
  periodLabel,
  registrationChip,
  shortDate,
  timelineTone,
  tuitionLineDescription,
} from "./family-view";
import type { FamilyEnrollment, FamilyStudent } from "@/lib/api/admin-families";

describe("autopayToggle", () => {
  const base = {
    active_count: 1,
    total_count: 2,
    card_last4: "4242",
    card_label: "Visa",
    next_charge_on: "2026-09-08",
    next_charge_invoice_id: "inv-1",
    last_failure: null,
  };
  it("on: checked, enabled, shows card and next charge", () => {
    expect(autopayToggle({ ...base, state: "on" })).toEqual({
      checked: true,
      disabled: false,
      label: "On",
      hint: "Visa ••4242 · next charge Sep 8",
    });
  });
  it("partial: checked with a count", () => {
    expect(autopayToggle({ ...base, state: "partial" }).label).toBe("On for 1 of 2");
  });
  it("off: unchecked, enabled", () => {
    expect(autopayToggle({ ...base, state: "off", next_charge_on: null })).toMatchObject({
      checked: false,
      disabled: false,
      label: "Off",
    });
  });
  it("needs_consent: disabled with the invite hint", () => {
    expect(
      autopayToggle({
        ...base,
        state: "needs_consent",
        card_last4: null,
        card_label: null,
        next_charge_on: null,
      }),
    ).toEqual({
      checked: false,
      disabled: true,
      label: "Off",
      hint: "Needs parent consent — send invite",
    });
  });
});

describe("dates", () => {
  it("shortDate renders an academy-local ISO date without a timezone shift", () => {
    expect(shortDate("2026-09-08")).toBe("Sep 8");
    expect(shortDate("2026-12-31T05:00:00Z")).toBe("Dec 31");
    expect(shortDate(null)).toBeNull();
    expect(shortDate("garbage")).toBeNull();
  });
  it("periodLabel renders YYYY-MM", () => {
    expect(periodLabel("2026-09")).toBe("Sep 2026");
    expect(periodLabel("weird")).toBe("weird");
  });
});

describe("labels and chips", () => {
  it("maps invoice actions", () => {
    expect(invoiceActionLabel("charge_card")).toBe("Charge card now");
    expect(invoiceActionLabel("discount_once")).toBe("One-time discount");
  });
  it("maps registration states onto real Chip variants", () => {
    expect(registrationChip("registered")).toEqual({ label: "Card on file", variant: "paid" });
    expect(registrationChip("invited")).toEqual({ label: "Invited", variant: "pending" });
    expect(registrationChip("not_invited")).toEqual({ label: "Not invited", variant: "manual" });
  });
  it("mutes comms rows", () => {
    expect(timelineTone({ kind: "comms", muted: true })).toBe("muted");
    expect(timelineTone({ kind: "money", muted: false })).toBe("money");
  });
});

describe("manual invoice defaults", () => {
  it("currentPeriod uses the viewer's own calendar month", () => {
    expect(currentPeriod(new Date(2026, 8, 12))).toBe("2026-09");
    expect(currentPeriod(new Date(2026, 0, 1))).toBe("2026-01");
  });
  it("defaultDueDate lands a week out and rolls the month", () => {
    expect(defaultDueDate(new Date(2026, 8, 12))).toBe("2026-09-19");
    expect(defaultDueDate(new Date(2026, 8, 28))).toBe("2026-10-05");
  });
  it("tuitionLineDescription matches the monthly generator's wording", () => {
    expect(tuitionLineDescription("2026-09")).toBe("Monthly tuition 2026-09");
  });
});

describe("enrollment pricing", () => {
  const enrollment: FamilyEnrollment = {
    enrollment_id: "enr-1",
    session_id: "ses-1",
    session_title: "Tue/Thu Intermediate",
    schedule: null,
    status: "active",
    monthly_price_cents: 12000,
    override_price_cents: null,
    autopay_status: null,
    recurring_discount: null,
    resume_on: null,
    actions: [],
  };
  it("prefers the override price", () => {
    expect(enrollmentPriceCents(enrollment)).toBe(12000);
    expect(enrollmentPriceCents({ ...enrollment, override_price_cents: 9000 })).toBe(9000);
    expect(enrollmentPriceCents({ ...enrollment, monthly_price_cents: null })).toBeNull();
  });
  it("flattens students into one labelled list", () => {
    const students: FamilyStudent[] = [
      { student_id: "stu-1", name: "Arjun", status: "active", enrollments: [enrollment] },
      { student_id: "stu-2", name: "Meera", status: "active", enrollments: [] },
    ];
    expect(enrollmentOptions(students)).toEqual([
      {
        enrollment_id: "enr-1",
        student_id: "stu-1",
        student_name: "Arjun",
        label: "Arjun · Tue/Thu Intermediate",
        price_cents: 12000,
        bill_period_price_cents: 12000,
      },
    ]);
  });
  it("quotes the session price for Bill this month, never the override", () => {
    expect(enrollmentBillPeriodPriceCents({ ...enrollment, override_price_cents: 15000 })).toBe(
      12000,
    );
    expect(enrollmentBillPeriodPriceCents({ ...enrollment, monthly_price_cents: null })).toBeNull();
  });
  it("falls back to Class when the session has no title", () => {
    const students: FamilyStudent[] = [
      {
        student_id: "stu-1",
        name: "Arjun",
        status: "active",
        enrollments: [{ ...enrollment, session_title: null }],
      },
    ];
    expect(enrollmentOptions(students)[0].label).toBe("Arjun · Class");
  });
});
