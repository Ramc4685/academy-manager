import { beforeEach, describe, expect, it, vi } from "vitest";

import { chargeAdminInvoiceAutopay } from "./admin";
import * as client from "./client";

function sentRequestId(spy: ReturnType<typeof vi.spyOn>, call: number): string {
  const init = spy.mock.calls[call][1] as { body: string };
  return JSON.parse(init.body).request_id;
}

describe("chargeAdminInvoiceAutopay retry safety (L1 should-fix 10)", () => {
  beforeEach(() => vi.restoreAllMocks());

  it("reuses the request id after a timeout so the server replays the first charge", async () => {
    const spy = vi
      .spyOn(client, "apiFetch")
      .mockRejectedValueOnce(new TypeError("Failed to fetch"))
      .mockResolvedValueOnce({ success: true } as never);

    await expect(chargeAdminInvoiceAutopay("inv-timeout")).rejects.toThrow();
    await chargeAdminInvoiceAutopay("inv-timeout");

    expect(sentRequestId(spy, 0)).toBe(sentRequestId(spy, 1));
  });

  it("mints a fresh id once the server gave a definite answer", async () => {
    const spy = vi.spyOn(client, "apiFetch").mockResolvedValue({ success: true } as never);

    await chargeAdminInvoiceAutopay("inv-done");
    await chargeAdminInvoiceAutopay("inv-done");

    expect(sentRequestId(spy, 0)).not.toBe(sentRequestId(spy, 1));
  });

  it("mints a fresh id after a 4xx refusal", async () => {
    const refusal = Object.assign(new Error("no card"), { status: 422 });
    const spy = vi
      .spyOn(client, "apiFetch")
      .mockRejectedValueOnce(refusal)
      .mockResolvedValueOnce({ success: true } as never);

    await expect(chargeAdminInvoiceAutopay("inv-refused")).rejects.toThrow();
    await chargeAdminInvoiceAutopay("inv-refused");

    expect(sentRequestId(spy, 0)).not.toBe(sentRequestId(spy, 1));
  });
});
