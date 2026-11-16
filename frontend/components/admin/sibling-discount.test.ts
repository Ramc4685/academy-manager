import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import {
  SiblingDiscountChip,
  siblingBadgeLabel,
  siblingFamilySummary,
} from "./sibling-discount";
import {
  parseFamilySiblingDiscount,
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
          enrollments: [row({ status: "not_eligible", reason: "only_one_child" })],
        },
        nameOf,
      ),
    ).toBeNull();
  });
});
