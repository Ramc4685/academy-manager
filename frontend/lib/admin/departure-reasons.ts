/**
 * Why a family left, as a closed vocabulary (issue #775).
 *
 * Mirrors `DepartureReasonCode` in
 * `backend/v2/contexts/enrollment/domain/departure_policy.py`. The backend is
 * the authority — it rejects anything outside the list — and there is no
 * endpoint that serves the vocabulary, so this file is the mirror. Keep the
 * two in sync; `backend/v2/tests/structural/
 * test_departure_reason_vocabulary_mirror.py` fails when they disagree, so a
 * backend-only edit cannot drift silently past review.
 *
 * The code rides ALONGSIDE the free-text reason, never instead of it: a code
 * cannot carry "Dad took a job in Austin". Both dialogs therefore keep the
 * note required and leave the code optional, with `other` as the deliberate
 * escape hatch (a vocabulary with no way out gets mis-coded).
 */

export type DepartureReasonCode =
  | "moved_away"
  | "schedule_conflict"
  | "cost"
  | "lost_interest"
  | "injury_or_health"
  | "switched_academy"
  | "coaching_fit"
  | "season_break"
  | "non_payment"
  | "other";

export const DEPARTURE_REASON_OPTIONS: { value: DepartureReasonCode; label: string }[] = [
  { value: "moved_away", label: "Moved away" },
  { value: "schedule_conflict", label: "Schedule conflict" },
  { value: "cost", label: "Cost" },
  { value: "lost_interest", label: "Lost interest" },
  { value: "injury_or_health", label: "Injury or health" },
  { value: "switched_academy", label: "Switched academy" },
  { value: "coaching_fit", label: "Coaching fit" },
  { value: "season_break", label: "Season break" },
  { value: "non_payment", label: "Non-payment" },
  { value: "other", label: "Other" },
];

/** The label the leaving report shows for a stored code. */
export function departureReasonLabel(code: string | null | undefined): string | null {
  if (!code) return null;
  return DEPARTURE_REASON_OPTIONS.find((option) => option.value === code)?.label ?? code;
}

/**
 * What a `<select>` value means on submit: the empty option is "not coded",
 * which the API takes as an omitted field rather than an empty string (the
 * backend's `DepartureReasonCode | None` rejects `""`).
 */
export function toReasonCode(value: string): DepartureReasonCode | undefined {
  return value === "" ? undefined : (value as DepartureReasonCode);
}
