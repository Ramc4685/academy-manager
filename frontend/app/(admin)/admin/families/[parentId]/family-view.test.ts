import { describe, expect, it } from "vitest";

import {
  autopayToggle,
  invoiceActionLabel,
  periodLabel,
  registrationChip,
  shortDate,
  timelineTone,
} from "./family-view";

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
