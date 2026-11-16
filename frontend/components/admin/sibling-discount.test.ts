import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import {
  periodMonthName,
  SiblingDiscountChip,
  siblingBadgeLabel,
  siblingFamilySummary,
} from "./sibling-discount";
import {
  parseFamilySiblingDiscount,
  type FamilySiblingDiscount,
  type SiblingDiscountEnrollment,
} from "@/lib/api/admin-families";

function row(over: Partial<SiblingDiscountEnrollment> = {}): SiblingDiscountEnrollment {
  return {
    enrollment_id: "enr-b",
    student_id: "stu-b",
    session_id: "sess-1",
    status: "discounted",
    reason: "sibling_discount",
    percent_bps: 1000,
    exclusion: null,
    billing_type: null,
    ...over,
  };
}

describe("siblingBadgeLabel", () => {
  it("words each status the backend decided", () => {
    expect(siblingBadgeLabel(row())).toBe("Sibling discount 10% (automatic)");
    expect(siblingBadgeLabel(row({ percent_bps: 1250 }))).toBe(
      "Sibling discount 12.5% (automatic)",
    );
    expect(siblingBadgeLabel(row({ status: "full_price", reason: "full_price_child" }))).toBe(
      "Pays full price (sibling discount)",
    );
    expect(
      siblingBadgeLabel(row({ status: "not_eligible", reason: "manual_discount_larger" })),
    ).toBe("Manual discount kept (larger than sibling 10%)");
  });

  it("shows nothing when off, not eligible or unknown", () => {
    expect(siblingBadgeLabel(undefined)).toBeNull();
    expect(siblingBadgeLabel(row({ status: "off", reason: "setting_off" }))).toBeNull();
    expect(siblingBadgeLabel(row({ status: "not_eligible", reason: "only_one_child" }))).toBeNull();
  });
});

describe("SiblingDiscountChip", () => {
  it("renders the badge for a discounted class", () => {
    const html = renderToStaticMarkup(createElement(SiblingDiscountChip, { row: row() }));
    expect(html).toContain('data-testid="sibling-discount-badge-enr-b"');
    expect(html).toContain("Sibling discount 10% (automatic)");
  });

  it("renders nothing without a decision", () => {
    expect(renderToStaticMarkup(createElement(SiblingDiscountChip, { row: undefined }))).toBe("");
  });
});

describe("parseFamilySiblingDiscount", () => {
  it("rejects a catch-all {} and other routes' bodies", () => {
    expect(parseFamilySiblingDiscount({})).toBeNull();
    expect(parseFamilySiblingDiscount(null)).toBeNull();
    expect(parseFamilySiblingDiscount({ enabled: true })).toBeNull();
    expect(parseFamilySiblingDiscount({ students: [], invoices: [] })).toBeNull();
  });

  it("drops partial rows instead of guessing", () => {
    const parsed = parseFamilySiblingDiscount({
      enabled: true,
      period: "2026-11",
      percent_bps: 1000,
      enrollments: [row(), { enrollment_id: "enr-x" }, { status: "discounted" }, row({ enrollment_id: "enr-y", status: "bogus" as never })],
    });
    expect(parsed?.enrollments.map((r) => r.enrollment_id)).toEqual(["enr-b"]);
  });
});

describe("siblingFamilySummary", () => {
  const names: Record<string, string> = { "stu-a": "Ava", "stu-b": "Ben", "stu-c": "Cleo" };
  const nameOf = (id: string) => names[id] ?? id;

  it("says who pays full price and who is discounted, once per child", () => {
    const summary = siblingFamilySummary(
      {
        period: "2026-11",
        enabled: true,
        percent_bps: 1000,
        next_period: null,
        enrollments: [
          row({ enrollment_id: "enr-a", student_id: "stu-a", status: "full_price", percent_bps: null }),
          row(),
          row({ enrollment_id: "enr-b2" }),
          row({ enrollment_id: "enr-c", student_id: "stu-c" }),
        ],
      },
      nameOf,
    );
    expect(summary).toBe("Sibling discount this month: Ava pays full price; Ben, Cleo get 10% off.");
  });

  it("still names a billed discount after the setting went off", () => {
    const view = parseFamilySiblingDiscount({
      period: "2026-11",
      enabled: false,
      percent_bps: null,
      enrollments: [row()],
    });
    expect(view && siblingBadgeLabel(view.enrollments[0])).toBe("Sibling discount 10% (automatic)");
    expect(view && siblingFamilySummary(view, nameOf)).toBe(
      "Sibling discount this month: Ben gets 10% off.",
    );
  });

  it("is null when nobody is full price or discounted", () => {
    expect(
      siblingFamilySummary(
        {
          period: "2026-11",
          enabled: true,
          percent_bps: 1000,
          next_period: null,
          enrollments: [row({ status: "not_eligible", reason: "only_one_child" })],
        },
        nameOf,
      ),
    ).toBeNull();
  });
});

/** Two children billed in November before the setting went on (made-up family). */
function invoicedBeforeSetting(): FamilySiblingDiscount {
  return {
    period: "2026-11",
    enabled: true,
    percent_bps: 1000,
    enrollments: [
      row({ enrollment_id: "enr-a", student_id: "stu-a", status: "not_eligible", reason: "already_invoiced", percent_bps: null }),
      row({ status: "not_eligible", reason: "already_invoiced", percent_bps: null }),
    ],
    next_period: {
      period: "2026-12",
      enrollments: [
        row({ enrollment_id: "enr-a", student_id: "stu-a", status: "full_price", reason: "full_price_child", percent_bps: null }),
        row(),
      ],
    },
  };
}

/** Ava on monthly invoices, Ben marked No charge. */
function oneChildOffTheRun(): FamilySiblingDiscount {
  return {
    period: "2026-11",
    enabled: true,
    percent_bps: 1000,
    enrollments: [
      row({ enrollment_id: "enr-a", student_id: "stu-a", status: "not_eligible", reason: "already_invoiced", percent_bps: null }),
      row({ status: "not_eligible", reason: "not_billed_this_month", percent_bps: null, exclusion: "billing_type", billing_type: "NoCharge" }),
    ],
    next_period: {
      period: "2026-12",
      enrollments: [
        row({ enrollment_id: "enr-a", student_id: "stu-a", status: "not_eligible", reason: "only_one_child", percent_bps: null }),
        row({ status: "not_eligible", reason: "not_billed_this_month", percent_bps: null, exclusion: "billing_type", billing_type: "NoCharge" }),
      ],
    },
  };
}

describe("a switched-on sibling family never goes silent", () => {
  const names: Record<string, string> = { "stu-a": "Ava", "stu-b": "Ben" };
  const nameOf = (id: string) => names[id] ?? id;

  it("names the month", () => {
    expect(periodMonthName("2026-12")).toBe("December");
    expect(periodMonthName("2027-01")).toBe("January");
    expect(periodMonthName("soon")).toBe("soon");
  });

  it("previews next month for a month already invoiced", () => {
    const view = invoicedBeforeSetting();
    expect(siblingBadgeLabel(view.enrollments[0], view)).toBe(
      "From December: pays full price (sibling discount)",
    );
    expect(siblingBadgeLabel(view.enrollments[1], view)).toBe(
      "From December: sibling discount 10% (automatic)",
    );
    expect(siblingFamilySummary(view, nameOf)).toBe(
      "November was already invoiced without the sibling discount. From December: Ava pays full price · Ben 10% off.",
    );
  });

  it("says plainly why a class is off the monthly invoices", () => {
    const view = oneChildOffTheRun();
    expect(siblingBadgeLabel(view.enrollments[1], view)).toBe(
      "Not on monthly invoices: marked No charge, so no sibling discount",
    );
    // Next month has nothing to promise Ava, so her badge says November was billed.
    expect(siblingBadgeLabel(view.enrollments[0], view)).toBe(
      "November already invoiced without the sibling discount",
    );
    expect(siblingFamilySummary(view, nameOf)).toBe(
      "November was already invoiced without the sibling discount. Ben: not on monthly invoices (marked No charge), so no sibling discount.",
    );
  });

  it("words every exclusion", () => {
    const view = oneChildOffTheRun();
    const label = (over: Partial<SiblingDiscountEnrollment>) =>
      siblingBadgeLabel(row({ status: "not_eligible", reason: "not_billed_this_month", percent_bps: null, ...over }), view);
    expect(label({ exclusion: "paused" })).toBe("Not on monthly invoices: paused this month, so no sibling discount");
    expect(label({ exclusion: "billing_type", billing_type: "Waived" })).toBe(
      "Not on monthly invoices: tuition waived, so no sibling discount",
    );
    expect(label({ exclusion: "billing_type", billing_type: "Prepaid" })).toContain("billing type Prepaid");
    expect(label({ exclusion: "deferral" })).toContain("billing deferred this month");
    expect(label({ exclusion: "pending_cancellation" })).toContain("cancels before this month");
    expect(label({ exclusion: "skip_period" })).toContain("skipped this month");
    expect(label({ exclusion: "no_class_fee" })).toContain("the class has no monthly fee");
    expect(label({ exclusion: "not_active" })).toContain("not active");
    expect(siblingBadgeLabel(row({ status: "not_eligible", reason: "only_one_child" }), view)).toBe(
      "No sibling discount: the only child on monthly invoices",
    );
    expect(siblingBadgeLabel(row({ status: "not_eligible", reason: "one_class_per_child" }), view)).toBe(
      "No sibling discount on this class (one class per child)",
    );
  });

  it("does not contradict a child already discounted on another class", () => {
    const view: FamilySiblingDiscount = {
      period: "2026-11",
      enabled: true,
      percent_bps: 1000,
      next_period: null,
      enrollments: [
        row({ enrollment_id: "enr-a", student_id: "stu-a", status: "full_price", reason: "full_price_child", percent_bps: null }),
        row(),
        row({ enrollment_id: "enr-b2", status: "not_eligible", reason: "not_billed_this_month", percent_bps: null, exclusion: "paused" }),
      ],
    };
    expect(siblingFamilySummary(view, nameOf)).toBe(
      "Sibling discount this month: Ava pays full price; Ben gets 10% off.",
    );
    expect(siblingBadgeLabel(row({ status: "not_eligible", reason: "not_billed_this_month", exclusion: null }), view)).toBe(
      "Not on monthly invoices: left off this month's run, so no sibling discount",
    );
  });

  it("stays quiet when the setting is off or there is one child", () => {
    const off = { ...invoicedBeforeSetting(), enabled: false, next_period: null };
    expect(siblingBadgeLabel(off.enrollments[1], off)).toBeNull();
    expect(siblingFamilySummary(off, nameOf)).toBeNull();
    const single = { ...invoicedBeforeSetting(), enrollments: [invoicedBeforeSetting().enrollments[1]] };
    expect(siblingBadgeLabel(single.enrollments[0], single)).toBeNull();
    expect(siblingFamilySummary(single, nameOf)).toBeNull();
  });

  it("parses the next month and the exclusion", () => {
    const parsed = parseFamilySiblingDiscount(oneChildOffTheRun());
    expect(parsed?.next_period?.period).toBe("2026-12");
    expect(parsed?.enrollments[1].exclusion).toBe("billing_type");
    expect(parsed?.enrollments[1].billing_type).toBe("NoCharge");
    expect(parseFamilySiblingDiscount({ enabled: true, enrollments: [], next_period: { period: 7 } })?.next_period).toBeNull();
  });
});
