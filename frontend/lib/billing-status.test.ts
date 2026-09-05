import { describe, expect, it } from "vitest";
import { invoiceStatusChip, normalizeInvoiceStatus } from "./billing-status";

describe("normalizeInvoiceStatus", () => {
  it.each([
    ["draft", "draft"],
    ["open", "open"],
    ["partially_paid", "partially_paid"],
    ["paid", "paid"],
    ["void", "void"],
    ["succeeded", "paid"],
    ["refunded", "paid"],
    ["partially_refunded", "paid"],
    ["pending", "open"],
    ["failed", "open"],
    ["waived", "void"],
    ["cancelled", "void"],
    ["expired", "void"],
  ] as const)("maps %s to %s", (raw, expected) => {
    expect(normalizeInvoiceStatus(raw)).toBe(expected);
  });

  it("treats unknown, empty and missing values as open", () => {
    expect(normalizeInvoiceStatus("something_new")).toBe("open");
    expect(normalizeInvoiceStatus("")).toBe("open");
    expect(normalizeInvoiceStatus(null)).toBe("open");
    expect(normalizeInvoiceStatus(undefined)).toBe("open");
  });

  it("is case and whitespace tolerant", () => {
    expect(normalizeInvoiceStatus(" PAID ")).toBe("paid");
    expect(normalizeInvoiceStatus("Succeeded")).toBe("paid");
  });
});

describe("invoiceStatusChip", () => {
  it.each([
    ["draft", { variant: "draft", label: "DRAFT" }],
    ["open", { variant: "pending", label: "OPEN" }],
    ["pending", { variant: "pending", label: "OPEN" }],
    ["failed", { variant: "pending", label: "OPEN" }],
    ["partially_paid", { variant: "partial", label: "PARTIALLY PAID" }],
    ["paid", { variant: "paid", label: "PAID" }],
    ["succeeded", { variant: "paid", label: "PAID" }],
    ["refunded", { variant: "paid", label: "PAID" }],
    ["partially_refunded", { variant: "paid", label: "PAID" }],
    ["void", { variant: "waived", label: "VOID" }],
    ["waived", { variant: "waived", label: "VOID" }],
    ["cancelled", { variant: "waived", label: "VOID" }],
    ["expired", { variant: "waived", label: "VOID" }],
  ] as const)("chips %s", (raw, expected) => {
    expect(invoiceStatusChip(raw)).toEqual(expected);
  });

  it("falls back to OPEN for unknown values", () => {
    expect(invoiceStatusChip(null)).toEqual({ variant: "pending", label: "OPEN" });
    expect(invoiceStatusChip("mystery")).toEqual({ variant: "pending", label: "OPEN" });
  });
});
