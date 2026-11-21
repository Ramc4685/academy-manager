import { describe, expect, it } from "vitest";

import { payslipChipFor } from "./payslip-chip";

describe("payslipChipFor", () => {
  it("labels an approved-but-unpaid payslip APPROVED, not DRAFT", () => {
    const chip = payslipChipFor("approved");
    expect(chip.label).toBe("APPROVED");
    expect(chip.variant).toBe("approved");
  });

  it("labels a paid payslip PAID", () => {
    const chip = payslipChipFor("paid");
    expect(chip.label).toBe("PAID");
    expect(chip.variant).toBe("paid");
  });

  it("labels a draft payslip DRAFT", () => {
    const chip = payslipChipFor("draft");
    expect(chip.label).toBe("DRAFT");
    expect(chip.variant).toBe("draft");
  });

  it("labels a not-yet-generated payslip distinctly from draft", () => {
    const chip = payslipChipFor("not_generated");
    expect(chip.label).toBe("NOT GENERATED");
    expect(chip.variant).toBe("draft");
  });

  it("falls back to DRAFT when no payroll status is known for the coach", () => {
    const chip = payslipChipFor(undefined);
    expect(chip.label).toBe("DRAFT");
    expect(chip.variant).toBe("draft");
  });
});
