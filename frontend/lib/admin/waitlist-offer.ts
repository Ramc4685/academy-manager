import { formatAcademyDateTime } from "@/lib/format/academy-time";

/**
 * X2: an `offered` waitlist row is holding a seat for a family that has not
 * answered yet. Admin views show when that hold ends (the hourly sweep then
 * offers the seat to the next family), on the academy's clock, the same one
 * the family's email uses.
 */

/** X2: shown under a seatless offer so staff know a hold is at stake. */
export const SEATLESS_OFFER_NOTE = "Class full of holds: a held seat is reclaimed only if they confirm";

export function offerExpiryLabel(
  iso: string | null | undefined,
  academyTimezone?: string | null,
): string | null {
  if (!iso) return null;
  const when = formatAcademyDateTime(iso, academyTimezone);
  return when ? `Held until ${when}` : null;
}
