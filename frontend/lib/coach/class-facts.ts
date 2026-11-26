import type { CoachAgeBand, CoachScheduleEntry } from "@/lib/api/coach";

/** "Ages 8–12", "Ages 13+", "Up to age 9"; null when the class has no age span. */
export function ageBandLabel(band: CoachAgeBand | null | undefined): string | null {
  const min = band?.min_age ?? null;
  const max = band?.max_age ?? null;
  if (min !== null && max !== null) return min === max ? `Age ${min}` : `Ages ${min}–${max}`;
  if (min !== null) return `Ages ${min}+`;
  if (max !== null) return `Up to age ${max}`;
  return null;
}

/** Quiet roster-row line: "Age 9 · Grip & Control"; empty when neither is known. */
export function rosterRowMeta(row: { age_years?: number | null; level_name?: string | null }): string {
  return [row.age_years != null ? `Age ${row.age_years}` : "", row.level_name ?? ""]
    .filter(Boolean)
    .join(" · ");
}

export function headcountLabel(count: number): string {
  return `${count} ${count === 1 ? "child" : "children"}`;
}

/** The teaching plan for a class date (the plan route is per day, not per class). */
export function coachPlanHref(date: string): string {
  return `/coach/today/plan?date=${encodeURIComponent(date)}`;
}

/** "8 children · Ages 8–12" for a Sessions row; empty when neither is known. */
export function classFacts(session: Pick<CoachScheduleEntry, "enrolled_count" | "age_band">): string {
  return [
    typeof session.enrolled_count === "number" ? headcountLabel(session.enrolled_count) : "",
    ageBandLabel(session.age_band) ?? "",
  ]
    .filter(Boolean)
    .join(" · ");
}
