import { describe, expect, it } from "vitest";

import {
  MANUAL_PAYMENT_METHODS,
  manualMethodLabel,
  manualMethodOptions,
  resolveManualMethod,
} from "./payment-methods";

const BLNO_SIX = [
  { value: "cash", label: "Cash" },
  { value: "check", label: "Check" },
  { value: "zelle", label: "Zelle" },
  { value: "venmo", label: "Venmo" },
  { value: "bank_transfer", label: "Bank transfer" },
  { value: "other", label: "Other" },
];

describe("manual payment methods (row 22)", () => {
  it("keeps the six methods, labels and order every dialog hardcoded before (BLNO pin)", () => {
    expect([...MANUAL_PAYMENT_METHODS]).toEqual(BLNO_SIX.map((o) => o.value));
    expect(manualMethodOptions(["cash", "check", "zelle", "venmo", "bank_transfer", "other"])).toEqual(
      BLNO_SIX,
    );
  });

  it("offers all six while loading, on a failed read, or for an empty list", () => {
    expect(manualMethodOptions(undefined)).toEqual(BLNO_SIX);
    expect(manualMethodOptions(null)).toEqual(BLNO_SIX);
    expect(manualMethodOptions([])).toEqual(BLNO_SIX);
    expect(manualMethodOptions(["wire"])).toEqual(BLNO_SIX);
  });

  it("lists exactly the enabled methods in canonical order", () => {
    expect(manualMethodOptions(["other", "zelle", "bitcoin"]).map((o) => o.value)).toEqual([
      "zelle",
      "other",
    ]);
  });

  it("defaults to the first enabled method: cash for BLNO", () => {
    expect(resolveManualMethod(null, manualMethodOptions(undefined))).toBe("cash");
    expect(resolveManualMethod(null, manualMethodOptions(["venmo", "check"]))).toBe("check");
  });

  it("keeps a still-offered pick and snaps a withdrawn one back to the default", () => {
    expect(resolveManualMethod("zelle", manualMethodOptions(undefined))).toBe("zelle");
    expect(resolveManualMethod("cash", manualMethodOptions(["zelle", "other"]))).toBe("zelle");
  });
});

describe("manualMethodLabel (S19)", () => {
  it("reads stored methods as words, whatever their case", () => {
    expect(manualMethodLabel("bank_transfer")).toBe("Bank transfer");
    expect(manualMethodLabel("BANK_TRANSFER")).toBe("Bank transfer");
    expect(manualMethodLabel("cash")).toBe("Cash");
  });
  it("turns an unknown code into a sentence rather than shouting it", () => {
    expect(manualMethodLabel("money_order")).toBe("Money order");
  });
});
