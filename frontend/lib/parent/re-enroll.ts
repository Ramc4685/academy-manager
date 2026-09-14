/**
 * Returning-family re-enrolment (issue #827, from #775).
 *
 * A departed enrollment is history — never a seat and never money (see
 * `lib/format/departure-copy.ts`). But a family that left is exactly the
 * family most likely to come back, and until now the portal offered them
 * nothing: the departed row was read-only and the only way back in was to
 * phone the academy.
 *
 * Coming back means taking a seat in a class, and the ONLY parent-facing path
 * that creates one is the onboarding application → `POST /parent/checkout/start`
 * (`/parent/billing-enrollments` creates an autopay subscription against a
 * session TYPE; it puts nobody on a roster). So "Enroll in a class" sends the
 * family into the onboarding stepper with the child they already have pinned
 * to the url.
 *
 * Pinning the child is what keeps the acceptance promise "no duplicate student
 * is created": the stepper pre-fills the child step from that student's record,
 * and `PatchApplication` then re-binds the application to the existing
 * `student_id` by (parent, full name, date of birth) instead of authoring a new
 * one. The id in the url is a HINT for pre-filling only — the backend decides
 * the binding, and re-checks ownership, so a forged id buys nothing.
 */

export const RE_ENROLL_CHILD_PARAM = "child";

/** Where the departed row's "Enroll in a class" button points. */
export function reEnrollHref(studentId: string): string {
  return `/parent/onboarding?${RE_ENROLL_CHILD_PARAM}=${encodeURIComponent(studentId)}`;
}

/**
 * The pre-bound child id in an onboarding url, or null when there is none.
 *
 * Null for a plain `/parent/onboarding` visit and for an empty value, so a
 * first-time family sees the untouched "add a new child" form.
 */
export function reEnrollChildId(search: string): string | null {
  const value = new URLSearchParams(search).get(RE_ENROLL_CHILD_PARAM);
  return value ? value : null;
}
