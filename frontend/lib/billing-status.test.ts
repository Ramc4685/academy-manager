import { describe, expect, it } from "vitest";
import {
  INVOICE_STATUS_FILTER_OPTIONS,
  invoiceStatusChip,
  matchesInvoiceStatusFilter,
  normalizeInvoiceStatus,
} from "./billing-status";

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

describe("status filter vocabulary", () => {
  it("offers exactly the five chip words, in ledger order", () => {
    expect(INVOICE_STATUS_FILTER_OPTIONS).toEqual([
      { value: "draft", label: "Draft" },
      { value: "open", label: "Open" },
      { value: "partially_paid", label: "Partially paid" },
      { value: "paid", label: "Paid" },
      { value: "void", label: "Void" },
    ]);
  });

  it("every filter option label matches its chip label, ignoring case", () => {
    for (const option of INVOICE_STATUS_FILTER_OPTIONS) {
      expect(invoiceStatusChip(option.value).label.toLowerCase()).toBe(option.label.toLowerCase());
    }
  });

  it.each([
    // The admin list still emits raw ledger statuses (succeeded, refunded, ...):
    // the Paid filter must reach every row that renders a PAID chip.
    ["paid", "succeeded", true],
    ["paid", "paid", true],
    ["paid", "refunded", true],
    ["paid", "partially_refunded", true],
    ["paid", "pending", false],
    ["open", "pending", true],
    ["open", "failed", true],
    ["open", "open", true],
    ["open", "mystery", true],
    ["open", "paid", false],
    ["void", "waived", true],
    ["void", "cancelled", true],
    ["void", "expired", true],
    ["void", "succeeded", false],
    ["partially_paid", "partially_paid", true],
    ["partially_paid", "paid", false],
    ["draft", "draft", true],
    ["draft", "open", false],
  ] as const)("filter %s vs raw %s -> %s", (filter, raw, expected) => {
    expect(matchesInvoiceStatusFilter(raw, filter)).toBe(expected);
  });

  it("matches everything when the filter is all", () => {
    expect(matchesInvoiceStatusFilter("succeeded", "all")).toBe(true);
    expect(matchesInvoiceStatusFilter(null, "all")).toBe(true);
  });
});
