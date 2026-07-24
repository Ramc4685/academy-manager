import { Chip } from "@/components/ds/chip";

export const OPEN_BILLING_STATUSES = new Set([
  "open",
  "unpaid",
  "partially_paid",
  "partial",
  "pending",
  "failed",
  "expired",
]);

export function StatusChip({ status }: { status: string }) {
  const normalized = status.toLowerCase();
  const variant =
    normalized === "active" || normalized === "succeeded"
      ? "enrolled"
      : normalized === "paid"
        ? "paid"
        : normalized === "paused"
          ? "paused"
          : normalized === "pending" ||
              normalized === "unpaid" ||
              normalized === "open"
            ? "pending"
            : normalized === "failed"
              ? "failed"
              : normalized === "partially_paid" || normalized === "partial"
                ? "partial"
                : "expired";
  return <Chip variant={variant} label={status.toUpperCase()} />;
}
