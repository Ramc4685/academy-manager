import type { ChipVariant } from "@/components/ds/chip";

/**
 * Maps backend request-status strings to Chip variants for the parent
 * Requests page (absences, makeups, trials). Kept as a pure function so it
 * can be unit-tested without mounting the page — the page itself only ever
 * displays whatever status/fee/timing the backend returns (no client-side
 * policy math).
 */
export function requestStatusChipVariant(status: string): ChipVariant {
  switch (status) {
    case "pending":
      return "pending";
    case "approved":
      return "approved";
    case "denied":
      return "denied";
    case "expired":
      return "expired";
    case "converted":
      return "converted";
    default:
      return "pending";
  }
}
