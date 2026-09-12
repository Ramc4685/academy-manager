import { Chip, type ChipVariant } from "@/components/ds/chip";

export const OPEN_BILLING_STATUSES = new Set([
  "open",
  "unpaid",
  "partially_paid",
  "partial",
  "pending",
  "failed",
  "expired",
]);

/**
 * Chip presentation for one status string on the student profile.
 *
 * Pure so it can be asserted directly (StatusChip.test.tsx). This panel is fed
 * both enrollment statuses and billing/subscription ones, so it stays
 * string-shaped and falls through to "expired" for anything unrecognized —
 * the behaviour every status but the hold pair had before #733.
 *
 * #733: `held` / `reclaim_pending` only started reaching this panel once the
 * student-detail read stopped dropping them. Falling through would have
 * painted a child who is merely on hold in the same colour as a withdrawn
 * one, so both map to the muted "ON HOLD" the class roster already uses
 * (sessions/[id]/RosterPanel.tsx ENROLL_CHIP).
 */
export function chipForStatus(status: string): {
  variant: ChipVariant;
  label: string;
} {
  const normalized = status.toLowerCase();
  if (normalized === "held" || normalized === "reclaim_pending") {
    return { variant: "paused", label: "ON HOLD" };
  }
  const variant: ChipVariant =
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
  return { variant, label: status.toUpperCase() };
}

export function StatusChip({ status }: { status: string }) {
  const { variant, label } = chipForStatus(status);
  return <Chip variant={variant} label={label} />;
}
