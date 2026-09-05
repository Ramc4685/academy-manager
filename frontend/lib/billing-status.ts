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
