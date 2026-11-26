import { describe, expect, it } from "vitest";

import {
  type BillingRulesView,
  canSaveRules,
  changesLateFee,
  diffForm,
  toForm,
  turnsLateFeeOn,
} from "./billing-rules-form";
import { formatCents, parseDollarsToCents } from "./money";

const MONEY = { format: formatCents, parse: parseDollarsToCents };

function withLateFee(cents: number | null): BillingRulesView {
  return {
    groups: [
      {
        key: "late_payments",
        title: "Late payments",
        note: null,
        rows: [
          {
            key: "late_fee_cents",
            label: "Late fee",
            editable: true,
            value: cents,
            unit: "cents",
            min_value: 0,
            max_value: 100000,
            display: null,
            detail: null,
          },
        ],
      },
    ],
  };
}

function lateFeeDiff(view: BillingRulesView, dollars: string) {
  return diffForm(view, { ...toForm(view), late_fee_cents: dollars }, MONEY);
}

describe("late fee acknowledgement (S31)", () => {
  it("a change to a fee that is already on needs the tick (persona: 5 -> 6 saved at once)", () => {
    const stored = withLateFee(500);
    const diff = lateFeeDiff(stored, "6.00");
    expect(turnsLateFeeOn(stored, diff)).toBe(false);
    expect(changesLateFee(stored, diff)).toBe(true);
    expect(canSaveRules(diff, changesLateFee(stored, diff), false)).toBe(false);
    expect(canSaveRules(diff, changesLateFee(stored, diff), true)).toBe(true);
  });

  it("turning a fee on from $0 still needs the tick", () => {
    const stored = withLateFee(0);
    const diff = lateFeeDiff(stored, "15.00");
    expect(changesLateFee(stored, diff)).toBe(true);
    expect(canSaveRules(diff, changesLateFee(stored, diff), false)).toBe(false);
  });

  it("turning the fee off or leaving it alone never asks", () => {
    const stored = withLateFee(500);
    expect(changesLateFee(stored, lateFeeDiff(stored, "0"))).toBe(false);
    expect(changesLateFee(stored, lateFeeDiff(stored, "5.00"))).toBe(false);
  });
});
