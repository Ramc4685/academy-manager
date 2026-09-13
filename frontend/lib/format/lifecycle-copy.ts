/**
 * Person-lifecycle chip copy (issue #773).
 *
 * The backend derives ONE state per person from their enrollments, holds,
 * pending cancels and attendance (`backend/v2/contexts/enrollment/domain/
 * lifecycle.py`). Every persona renders it through this module so admin,
 * parent and coach cannot drift into three vocabularies for one fact — which
 * is how `students.status` ended up meaning nothing at all.
 *
 * `lifecycle_as_of` is a CALENDAR date ("2026-10-15"), never an instant: a
 * resume date has to read as the same day for the family, the coach and the
 * admin, so it is never run through the academy-timezone formatters.
 */

import type { ChipVariant } from "@/components/ds/chip";

export type PersonLifecycle =
  | "active"
  | "at_risk"
  | "paused"
  | "on_hold"
  | "pending_cancel"
  | "left"
  | "never_enrolled"
  | "trial";

const ISO_DATE = /^(\d{4})-(\d{2})-(\d{2})$/;

/** "Oct 15, 2026" for a plain ISO date; "" when it is missing or malformed. */
export function formatLifecycleDate(asOf: string | null | undefined): string {
  const match = asOf?.trim().match(ISO_DATE);
  if (!match) return "";
  const [, year, month, day] = match;
  const instant = new Date(Date.UTC(Number(year), Number(month) - 1, Number(day)));
  if (Number.isNaN(instant.getTime())) return "";
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
    timeZone: "UTC",
  }).format(instant);
}

interface LifecycleSpec {
  label: string;
  variant: ChipVariant;
  /** How the date reads when there is one. */
  dated?: (day: string) => string;
}

const SPECS: Record<PersonLifecycle, LifecycleSpec> = {
  active: { label: "ACTIVE", variant: "enrolled" },
  at_risk: {
    label: "AT RISK",
    variant: "approval",
    dated: (day) => `AT RISK · last seen ${day}`,
  },
  paused: {
    label: "PAUSED",
    variant: "paused",
    dated: (day) => `PAUSED until ${day}`,
  },
  on_hold: {
    label: "ON HOLD",
    variant: "pending",
    dated: (day) => `ON HOLD until ${day}`,
  },
  pending_cancel: {
    label: "ENDING",
    variant: "closing",
    dated: (day) => `ENDS ${day}`,
  },
  left: { label: "LEFT", variant: "expired", dated: (day) => `LEFT ${day}` },
  never_enrolled: { label: "NOT ENROLLED", variant: "draft" },
  trial: { label: "TRIAL", variant: "waitlist" },
};

/** The filters /admin/students shows by default: everyone still on the books. */
export const OPERATIONAL_LIFECYCLES: PersonLifecycle[] = [
  "active",
  "on_hold",
  "paused",
  "at_risk",
];

/** Every state, in the order the directory filter bar lists them. */
export const ALL_LIFECYCLES: PersonLifecycle[] = [
  "active",
  "at_risk",
  "on_hold",
  "paused",
  "pending_cancel",
  "left",
  "never_enrolled",
  "trial",
];

function spec(state: string | null | undefined): LifecycleSpec {
  if (!state) {
    // A payload from before #773 (a cached page, a rolled-back backend) has
    // no lifecycle at all. Render the row without a chip rather than throwing
    // — a crashed table is strictly worse than a missing badge.
    return { label: "", variant: "draft" };
  }
  return (
    SPECS[state as PersonLifecycle] ?? {
      // A state this build does not know about is shown verbatim rather than
      // hidden: an unrenderable row is how held students vanished in #714.
      label: state.replace(/_/g, " ").toUpperCase(),
      variant: "draft" as ChipVariant,
    }
  );
}

/** Chip label, with the date folded in when the state carries one. */
export function lifecycleLabel(
  state: string | null | undefined,
  asOf?: string | null,
): string {
  const found = spec(state);
  const day = formatLifecycleDate(asOf);
  return day && found.dated ? found.dated(day) : found.label;
}

export function lifecycleVariant(state: string | null | undefined): ChipVariant {
  return spec(state).variant;
}

/** Sentence-case name for filter buttons and tiles ("On hold", "At risk"). */
export function lifecycleName(state: string | null | undefined): string {
  const label = spec(state).label.split(" · ")[0];
  return label.charAt(0) + label.slice(1).toLowerCase();
}
