import type { ParentHomeNextSession } from "@/lib/api/parent-home";

export interface NextClassDetail {
  label: string;
  value: string;
}

export interface NextClassDetails {
  /** S45: true until the child's first attended class. */
  firstClass: boolean;
  rows: NextClassDetail[];
  directionsHref: string | null;
}

/** A maps search link for the stored address; any phone opens it in its maps app. */
export function directionsHref(address: string | null | undefined): string | null {
  const clean = address?.trim();
  return clean ? `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(clean)}` : null;
}

/** What Home shows below the next-class card; null when there is nothing to show. */
export function nextClassDetails(
  next: ParentHomeNextSession | null | undefined,
  firstClassPending: boolean | undefined,
): NextClassDetails | null {
  if (!next) return null;
  const rows: NextClassDetail[] = [];
  if (next.venue_address) rows.push({ label: "Where", value: next.venue_address });
  if (next.parking_notes) rows.push({ label: "Parking", value: next.parking_notes });
  if (next.what_to_bring) rows.push({ label: "What to bring and wear", value: next.what_to_bring });
  if (next.arrival_minutes_before)
    rows.push({ label: "Arrive", value: `${next.arrival_minutes_before} minutes early` });
  if (next.coach_name) rows.push({ label: "Coach", value: next.coach_name });
  const href = directionsHref(next.venue_address);
  if (rows.length === 0 && !href) return null;
  return { firstClass: Boolean(firstClassPending), rows, directionsHref: href };
}
