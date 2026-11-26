import { describe, expect, it } from "vitest";

import { autopayConfigurable, emptyInvoicesCopy } from "@/lib/parent/payments-page";

describe("parent payments page (S24)", () => {
  it("hides autopay when no class can start or show one", () => {
    expect(autopayConfigurable([])).toBe(false);
    expect(
      autopayConfigurable([
        { autopay_offer: "manual_payments" },
        { autopay_offer: "free_class" },
        { autopay_offer: "available", departed: true },
      ]),
    ).toBe(false);
  });

  it("shows autopay when a class offers it or one is already set up", () => {
    expect(autopayConfigurable([{ autopay_offer: "available" }])).toBe(true);
    expect(autopayConfigurable([{ autopay_offer: null }])).toBe(true);
    expect(
      autopayConfigurable([{ autopay_offer: "unavailable", autopay_enrollment_status: "active" }]),
    ).toBe(true);
  });

  it("tells an empty family when the first invoice comes and how to pay", () => {
    const online = emptyInvoicesCopy(false);
    expect(online.body).toMatch(/once a class is confirmed/);
    expect(online.body).toMatch(/card or bank account/);
    const manual = emptyInvoicesCopy(true);
    expect(manual.body).toMatch(/in person/);
    expect(manual.body).not.toMatch(/autopay/);
  });
});
