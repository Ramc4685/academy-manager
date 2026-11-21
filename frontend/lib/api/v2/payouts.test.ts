import { describe, it, expect, vi, beforeEach } from "vitest";
import {
  approvePayoutPeriod,
  markPaidInput,
  markPayoutPeriodPaid,
  PAYOUT_CONFLICT_MESSAGE,
  payoutErrorMessage,
  recomputePayoutPeriod,
  reopenPayoutPeriod,
} from "./payouts";
import * as client from "../client";

describe("markPayoutPeriodPaid", () => {
  beforeEach(() => vi.restoreAllMocks());
  it("POSTs to the mark-paid route with payment body", async () => {
    const spy = vi.spyOn(client, "apiFetch").mockResolvedValue({ period_id: "p1", status: "paid" } as never);
    await markPayoutPeriodPaid("p1", {
      method: "bank_transfer", paid_at: "2026-07-01T00:00:00Z", amount_cents: 45000, reference: "py_1", expected_version: 2,
    });
    expect(spy).toHaveBeenCalledWith(
      "/admin/payout-periods/p1/mark-paid",
      expect.objectContaining({ method: "POST" }),
    );
  });
});

describe("payout writes carry the version on screen", () => {
  beforeEach(() => vi.restoreAllMocks());
  it("sends expected_version on approve, recompute and reopen", async () => {
    const spy = vi.spyOn(client, "apiFetch").mockResolvedValue({} as never);
    await approvePayoutPeriod("p1", 3);
    await recomputePayoutPeriod("p1", 4);
    await reopenPayoutPeriod("p1", "wrong rate", 5);
    expect(spy.mock.calls.map(([, init]) => JSON.parse(String(init?.body)))).toEqual([
      { expected_version: 3 },
      { expected_version: 4 },
      { reason: "wrong rate", expected_version: 5 },
    ]);
  });
});

describe("payoutErrorMessage", () => {
  it("turns a lost race into the reload prompt and keeps other messages", () => {
    const conflict = Object.assign(new Error("payout period changed (version 2)"), {
      code: "Finance.PayoutPeriodConflict",
    });
    expect(payoutErrorMessage(conflict)).toBe(PAYOUT_CONFLICT_MESSAGE);
    expect(PAYOUT_CONFLICT_MESSAGE).toMatch(/Someone else changed this payout/);
    expect(payoutErrorMessage(new Error("reason is required"))).toBe("reason is required");
  });
});

describe("markPaidInput", () => {
  it("submits the version the dialog opened on with the amount it showed", () => {
    expect(
      markPaidInput({
        method: "check",
        paidAt: "2026-07-01T00:00:00Z",
        amount: "450.10",
        reference: "",
        versionAtOpen: 3,
      }),
    ).toEqual({
      method: "check",
      paid_at: "2026-07-01T00:00:00.000Z",
      amount_cents: 45010,
      reference: null,
      expected_version: 3,
    });
  });
});
