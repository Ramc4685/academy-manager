import { describe, expect, it } from "vitest";

import type { FamilyIndexMoney } from "@/lib/api/admin-families";

import {
  effectiveMoneyView,
  familyMoneyDisplay,
  isViewingAs,
  serverMoneyView,
} from "./family-money-view";

const MONEY: FamilyIndexMoney = {
  balance_cents: 6000,
  open_invoice_count: 2,
  overdue_invoice_count: 1,
  overdue_cents: 4000,
  oldest_overdue_due_on: "2026-09-01",
  last_failed_payment_at: null,
};

describe("serverMoneyView", () => {
  it("reads money_view, falling back to money_visible for older payloads", () => {
    expect(serverMoneyView({ money_view: "flag", money_visible: false })).toBe("flag");
    expect(serverMoneyView({ money_visible: true })).toBe("amounts");
    expect(serverMoneyView({ money_visible: false })).toBe("none");
  });
});

describe("effectiveMoneyView (owner Viewing as preview)", () => {
  it("narrows amounts to the flag when previewing front desk", () => {
    expect(effectiveMoneyView("amounts", "self")).toBe("amounts");
    expect(effectiveMoneyView("amounts", "billing")).toBe("amounts");
    expect(effectiveMoneyView("amounts", "front_desk")).toBe("flag");
  });

  it("never widens what the server allowed", () => {
    for (const as of ["self", "billing", "front_desk"] as const) {
      expect(effectiveMoneyView("flag", as)).toBe("flag");
      expect(effectiveMoneyView("none", as)).toBe("none");
    }
  });

  it("only accepts the three preview ids", () => {
    expect(isViewingAs("front_desk")).toBe(true);
    expect(isViewingAs("owner")).toBe(false);
    expect(isViewingAs(null)).toBe(false);
  });
});

describe("familyMoneyDisplay per role", () => {
  it("owner, admin and billing see the amount", () => {
    expect(familyMoneyDisplay({ money: MONEY, owes_money: true }, "amounts")).toEqual({
      kind: "amount",
      balanceCents: 6000,
      overdueCents: 4000,
      overdueCount: 1,
      openCount: 2,
    });
  });

  it("front desk sees only the flag from a redacted payload", () => {
    expect(familyMoneyDisplay({ money: null, owes_money: true }, "flag")).toEqual({ kind: "owes" });
    expect(familyMoneyDisplay({ money: null, owes_money: false }, "flag")).toEqual({
      kind: "clear",
    });
  });

  it("unreadable money is unknown, never zero or paid up", () => {
    expect(familyMoneyDisplay({ money: null, owes_money: null }, "amounts")).toEqual({
      kind: "unknown",
    });
    expect(familyMoneyDisplay({ money: null, owes_money: null }, "flag")).toEqual({
      kind: "unknown",
    });
    expect(familyMoneyDisplay({ money: null }, "flag")).toEqual({ kind: "unknown" });
  });

  it("an owner previewing front desk on an older payload derives the flag", () => {
    expect(familyMoneyDisplay({ money: MONEY }, "flag")).toEqual({ kind: "owes" });
    expect(familyMoneyDisplay({ money: { ...MONEY, balance_cents: 0 } }, "flag")).toEqual({
      kind: "clear",
    });
  });

  it("an explicit unknown flag is never re-derived from an amount sent alongside it", () => {
    expect(familyMoneyDisplay({ money: MONEY, owes_money: null }, "flag")).toEqual({
      kind: "unknown",
    });
    expect(familyMoneyDisplay({ money: MONEY, owes_money: false }, "flag")).toEqual({
      kind: "clear",
    });
  });

  it("hidden when the caller may see no money", () => {
    expect(familyMoneyDisplay({ money: MONEY, owes_money: true }, "none")).toEqual({
      kind: "hidden",
    });
  });
});
