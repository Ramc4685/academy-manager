import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { OverviewTab } from "@/app/(admin)/admin/families/[parentId]/OverviewTab";
import type {
  FamilyIndexRow,
  FamilyMoneyView,
  FamilyRecordView,
} from "@/lib/api/admin-families";
import { effectiveMoneyView, familyMoneyDisplay, serverMoneyView } from "@/lib/family-money-view";

import { FamilyMoneyCell, FamilyOwesFlag } from "./family-money";
import { ViewingAsControl } from "./viewing-as";

/*
 * Per-role rendering of the family money display (L2b, #553). Each role gets
 * the payload the server actually sends it (see
 * backend/v2/tests/interface/test_admin_family_index_staff_tiers.py): owner,
 * admin and billing get amounts; front desk gets `money: null` plus
 * `owes_money`.
 */

const ROW: FamilyIndexRow = {
  family_id: "fam-1",
  parent_name: "Testparent One",
  email: null,
  phone: null,
  has_account: true,
  stage: "active",
  children: [],
  card_on_file: true,
  registration: "registered",
  money: {
    balance_cents: 6000,
    open_invoice_count: 1,
    overdue_invoice_count: 1,
    overdue_cents: 6000,
    oldest_overdue_due_on: "2026-09-01",
    last_failed_payment_at: null,
  },
  owes_money: true,
  matched_parent: false,
};

type Role = "owner" | "admin" | "billing" | "front_desk";

function payloadFor(role: Role): { row: FamilyIndexRow; view: FamilyMoneyView } {
  if (role === "front_desk") {
    return { row: { ...ROW, money: null, owes_money: true }, view: "flag" };
  }
  return { row: ROW, view: "amounts" };
}

function renderCell(row: FamilyIndexRow, view: FamilyMoneyView): string {
  return renderToStaticMarkup(
    createElement(FamilyMoneyCell, { display: familyMoneyDisplay(row, view), testId: "cell" }),
  );
}

describe("Families list balance cell per role", () => {
  it.each(["owner", "admin", "billing"] as const)("%s sees the amount", (role) => {
    const { row, view } = payloadFor(role);
    const html = renderCell(row, view);
    expect(html).toContain("$60.00");
    expect(html).not.toContain("Owes money");
  });

  it("front desk sees Owes money and no amount", () => {
    const { row, view } = payloadFor("front_desk");
    const html = renderCell(row, view);
    expect(html).toContain("Owes money");
    expect(html).not.toMatch(/\$\d/);
  });

  it("front desk sees Paid up for a family that owes nothing", () => {
    const html = renderCell({ ...ROW, money: null, owes_money: false }, "flag");
    expect(html).toContain("Paid up");
    expect(html).not.toMatch(/\$\d/);
  });

  it("unreadable money is a dash, never $0.00 or Paid up", () => {
    const html = renderCell({ ...ROW, money: null, owes_money: null }, "flag");
    expect(html).toContain("Balance unknown");
    expect(html).not.toContain("Paid up");
    expect(html).not.toContain("$0.00");
  });

  it("renders nothing when the caller may see no money", () => {
    expect(renderCell(ROW, "none")).toBe("");
  });
});

describe("Family header flag per role", () => {
  it("front desk gets the Owes money chip", () => {
    const { row, view } = payloadFor("front_desk");
    const html = renderToStaticMarkup(
      createElement(FamilyOwesFlag, { display: familyMoneyDisplay(row, view) }),
    );
    expect(html).toContain("family-record-owes-money");
    expect(html).toContain("Owes money");
  });

  it("amount viewers get no flag in the header (the balance is on Overview)", () => {
    const { row, view } = payloadFor("billing");
    const html = renderToStaticMarkup(
      createElement(FamilyOwesFlag, { display: familyMoneyDisplay(row, view) }),
    );
    expect(html).toBe("");
  });
});

function record(role: Role): FamilyRecordView {
  const { row, view } = payloadFor(role);
  return {
    generated_at: "2026-09-24T12:00:00Z",
    family_id: row.family_id,
    family: row,
    money_visible: view === "amounts",
    money_view: view,
    warnings: [],
  };
}

function renderOverview(rec: FamilyRecordView, view: FamilyMoneyView): string {
  return renderToStaticMarkup(
    createElement(OverviewTab, {
      record: rec,
      moneyView: view,
      billing: null,
      kids: [],
      onOpenChild: () => {},
    }),
  );
}

describe("Overview cards per role", () => {
  it.each(["owner", "admin", "billing"] as const)("%s sees the balance card", (role) => {
    const rec = record(role);
    const html = renderOverview(rec, serverMoneyView(rec));
    expect(html).toContain("family-overview-balance");
    expect(html).toContain("$60.00");
    expect(html).not.toContain("family-overview-owes");
  });

  it("front desk sees the flag card and no amount", () => {
    const rec = record("front_desk");
    const html = renderOverview(rec, serverMoneyView(rec));
    expect(html).toContain("family-overview-owes");
    expect(html).toContain("Owes money");
    expect(html).not.toContain("family-overview-balance");
    expect(html).not.toMatch(/\$\d/);
  });

  it("an owner previewing front desk sees what front desk sees", () => {
    const rec = record("owner");
    const html = renderOverview(rec, effectiveMoneyView(serverMoneyView(rec), "front_desk"));
    expect(html).toContain("Owes money");
    expect(html).not.toMatch(/\$\d/);
  });
});

describe("Viewing as control", () => {
  it("offers owner, billing and front desk", () => {
    const html = renderToStaticMarkup(
      createElement(ViewingAsControl, { value: "self", onChange: () => {} }),
    );
    expect(html).toContain("Viewing as");
    expect(html).toContain("Owner (you)");
    expect(html).toContain("Billing");
    expect(html).toContain("Front desk");
    expect(html).not.toContain("viewing-as-note");
  });

  it("says when a preview is on", () => {
    const html = renderToStaticMarkup(
      createElement(ViewingAsControl, { value: "front_desk", onChange: () => {} }),
    );
    expect(html).toContain("viewing-as-note");
    expect(html).toContain("Front desk sees it");
  });
});
