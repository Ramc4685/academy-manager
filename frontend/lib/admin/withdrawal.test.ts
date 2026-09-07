import { describe, expect, it } from "vitest";

import {
  NO_PAID_TUITION_MESSAGE,
  OWNER_GATE_404_MESSAGE,
  OWNER_ONLY_CREDIT_HINT,
  buildWithdrawRequest,
  defaultWithdrawalOutcome,
  withdrawErrorMessage,
  withdrawalOutcomeOptions,
} from "./withdrawal";

describe("withdrawalOutcomeOptions", () => {
  it("lets an owner pick every outcome", () => {
    const options = withdrawalOutcomeOptions(true);
    expect(options.map((o) => o.value)).toEqual(["credit", "refund", "adjustment"]);
    expect(options.every((o) => o.disabledReason === undefined)).toBe(true);
  });

  it("disables account credit for a plain admin and says why", () => {
    const options = withdrawalOutcomeOptions(false);
    const credit = options.find((o) => o.value === "credit");
    expect(credit?.disabledReason).toBe(OWNER_ONLY_CREDIT_HINT);
    expect(options.filter((o) => o.disabledReason).map((o) => o.value)).toEqual(["credit"]);
  });

  it("opens on credit for owners and refund for admins", () => {
    expect(defaultWithdrawalOutcome(true)).toBe("credit");
    expect(defaultWithdrawalOutcome(false)).toBe("refund");
  });
});

describe("buildWithdrawRequest", () => {
  it("sends every outcome through the same withdraw body", () => {
    expect(
      buildWithdrawRequest({ withdrawalDate: "2026-09-15", outcome: "credit", adminNote: " moving " }),
    ).toEqual({ effective_date: "2026-09-15", outcome: "credit", reason: "moving" });
  });

  it("falls back to a reason naming the outcome when the note is blank", () => {
    expect(
      buildWithdrawRequest({ withdrawalDate: "2026-09-15", outcome: "refund", adminNote: "" }),
    ).toEqual({ effective_date: "2026-09-15", outcome: "refund", reason: "Withdrawal refund" });
  });
});

describe("withdrawErrorMessage", () => {
  it("surfaces the server's 409 message so a second tab learns the row moved on", () => {
    expect(
      withdrawErrorMessage({
        status: 409,
        code: "Enrollment.NotWithdrawable",
        message: "Enrollment is already withdrawn; it cannot be withdrawn again.",
      }),
    ).toBe("Enrollment is already withdrawn; it cannot be withdrawn again.");
  });

  it("explains a codeless 404 as the owner-only credit refusal", () => {
    expect(withdrawErrorMessage({ status: 404, message: "Not found" })).toBe(
      OWNER_GATE_404_MESSAGE,
    );
  });

  it("does not blame permissions when the 404 carries a domain code", () => {
    expect(
      withdrawErrorMessage({
        status: 404,
        code: "Billing.PaymentNotFound",
        message: "paid payment snapshot not found",
      }),
    ).toBe(NO_PAID_TUITION_MESSAGE);
    expect(
      withdrawErrorMessage({
        status: 404,
        code: "Enrollment.NotFound",
        message: "enrollment missing",
      }),
    ).toBe("enrollment missing");
  });

  it("keeps other server messages and has a fallback", () => {
    expect(withdrawErrorMessage({ status: 500, message: "boom" })).toBe("boom");
    expect(withdrawErrorMessage(null)).toBe("Could not withdraw enrollment.");
    expect(withdrawErrorMessage({ status: 409, message: "  " })).toBe(
      "This enrollment was already withdrawn or cancelled.",
    );
  });
});
