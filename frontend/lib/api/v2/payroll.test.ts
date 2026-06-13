import { describe, it, expect, vi, beforeEach } from "vitest";
import { listMonthlyPayroll, generateMonthlyPayroll, recomputeMonthlyPayroll } from "./payroll";
import * as client from "../client";

describe("payroll client", () => {
  beforeEach(() => vi.restoreAllMocks());

  it("listMonthlyPayroll GETs the month route", async () => {
    const spy = vi.spyOn(client, "apiFetch").mockResolvedValue({ month: "2026-06", rows: [] } as never);
    await listMonthlyPayroll("2026-06");
    expect(spy).toHaveBeenCalledWith("/admin/payroll/2026-06", { method: "GET" });
  });

  it("generateMonthlyPayroll POSTs to generate", async () => {
    const spy = vi.spyOn(client, "apiFetch").mockResolvedValue({ month: "2026-06" } as never);
    await generateMonthlyPayroll("2026-06");
    expect(spy).toHaveBeenCalledWith("/admin/payroll/2026-06/generate", { method: "POST" });
  });

  it("recomputeMonthlyPayroll POSTs to recompute", async () => {
    const spy = vi.spyOn(client, "apiFetch").mockResolvedValue({ month: "2026-06" } as never);
    await recomputeMonthlyPayroll("2026-06");
    expect(spy).toHaveBeenCalledWith("/admin/payroll/2026-06/recompute", { method: "POST" });
  });
});
