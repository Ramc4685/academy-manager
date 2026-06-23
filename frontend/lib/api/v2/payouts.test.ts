import { describe, it, expect, vi, beforeEach } from "vitest";
import { markPayoutPeriodPaid } from "./payouts";
import * as client from "../client";

describe("markPayoutPeriodPaid", () => {
  beforeEach(() => vi.restoreAllMocks());
  it("POSTs to the mark-paid route with payment body", async () => {
    const spy = vi.spyOn(client, "apiFetch").mockResolvedValue({ period_id: "p1", status: "paid" } as never);
    await markPayoutPeriodPaid("p1", {
      method: "bank_transfer", paid_at: "2026-07-01T00:00:00Z", amount_cents: 45000, reference: "py_1",
    });
    expect(spy).toHaveBeenCalledWith(
      "/admin/payout-periods/p1/mark-paid",
      expect.objectContaining({ method: "POST" }),
    );
  });
});
