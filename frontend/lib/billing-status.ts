import type { ChipVariant } from "@/components/ds/chip";

/**
 * The one invoice status vocabulary shown to admins.
 *
 * The ledger stores a wider set (succeeded, refunded, pending, failed, waived,
 * cancelled, expired, ...). Those are collapsed at the view boundary so every
 * surface says the same five words (payments buckets spec §4).
 */
export type InvoiceStatus = "draft" | "open" | "partially_paid" | "paid" | "void";

const STATUS_ALIASES: Record<string, InvoiceStatus> = {
  draft: "draft",
  open: "open",
  partially_paid: "partially_paid",
  paid: "paid",
  void: "void",
  succeeded: "paid",
  refunded: "paid",
  partially_refunded: "paid",
  pending: "open",
  failed: "open",
  waived: "void",
  cancelled: "void",
  expired: "void",
};

/** Collapse a raw ledger/payment status onto the UI vocabulary; unknown → "open". */
export function normalizeInvoiceStatus(raw: string | null | undefined): InvoiceStatus {
  if (!raw) return "open";
  const key = raw.trim().toLowerCase();
  return STATUS_ALIASES[key] ?? "open";
}

export type InvoiceStatusChip = { variant: ChipVariant; label: string };

const STATUS_CHIPS: Record<InvoiceStatus, InvoiceStatusChip> = {
  draft: { variant: "draft", label: "DRAFT" },
  open: { variant: "pending", label: "OPEN" },
  partially_paid: { variant: "partial", label: "PARTIALLY PAID" },
  paid: { variant: "paid", label: "PAID" },
  void: { variant: "waived", label: "VOID" },
};

/** Chip spec for a raw status, normalised first. Returns a fresh object each call. */
export function invoiceStatusChip(raw: string | null | undefined): InvoiceStatusChip {
  return { ...STATUS_CHIPS[normalizeInvoiceStatus(raw)] };
}

/**
 * Status filter options for invoice/payment lists — the same five words the
 * chips use, so a filter can never disagree with what the row shows.
 */
export const INVOICE_STATUS_FILTER_OPTIONS: readonly { value: InvoiceStatus; label: string }[] = [
  { value: "draft", label: "Draft" },
  { value: "open", label: "Open" },
  { value: "partially_paid", label: "Partially paid" },
  { value: "paid", label: "Paid" },
  { value: "void", label: "Void" },
];

export type InvoiceStatusFilter = InvoiceStatus | "all";

/**
 * Whether a row with the raw ledger status `raw` belongs under the UI filter.
 *
 * The admin list still emits raw statuses (`succeeded`, `refunded`, `pending`,
 * `waived`, ...) and the backend list filter is an exact raw-string match, so
 * the UI-vocabulary filter is applied client-side through the same alias map
 * the chip uses: `paid` reaches succeeded|paid|partially_refunded|refunded.
 */
export function matchesInvoiceStatusFilter(
  raw: string | null | undefined,
  filter: InvoiceStatusFilter,
): boolean {
  if (filter === "all") return true;
  return normalizeInvoiceStatus(raw) === filter;
}
