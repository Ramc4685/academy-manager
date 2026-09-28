import { describe, expect, it } from "vitest";

import { invoicePrefixHint } from "./academy-panel";

describe("invoicePrefixHint (Settings overhaul P1 PR 2)", () => {
  it("shows what an invoice number looks like with the academy's prefix", () => {
    expect(invoicePrefixHint("BLNO")).toBe(
      "Invoice numbers look like BLNO-2026-09-0001. Set by CourtMastr.",
    );
  });

  it("says the prefix is not set rather than inventing one", () => {
    expect(invoicePrefixHint(null)).toMatch(/Not set yet/);
    expect(invoicePrefixHint("")).not.toMatch(/BLNO/);
  });
});
