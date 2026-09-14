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

/**
 * The sentinel the wizard's "No known conditions or allergies" checkbox
 * writes into `medical_notes` (see the child step). Mirrored here so a
 * pre-filled record reproduces exactly what the checkbox would have written.
 */
export const NO_MEDICAL_CONDITIONS_SENTINEL = "__none_declared__";

/** The picker option that means "this is somebody new". */
export const NEW_CHILD_SELECTION = "__new__";

/** One of the parent's existing children (`ParentSelfChild`, GET /parent/profile). */
export interface ExistingChild {
  student_id: string;
  full_name: string;
  date_of_birth: string | null;
  emergency_contact_name: string | null;
  emergency_contact_phone: string | null;
  medical_notes: string | null;
  no_medical_conditions: boolean;
}

/** The onboarding application's child step, as the wizard holds it. */
export interface ChildProfileDraft {
  first_name: string;
  last_name: string;
  date_of_birth: string;
  skill_level: "beginner" | "intermediate" | "advanced" | "";
  emergency_contact_name?: string | null;
  emergency_contact_phone?: string | null;
  medical_notes?: string | null;
}

/**
 * Which picker option the child step opens on.
 *
 * The pinned id only wins when it really is one of this parent's children —
 * `/parent/profile` is the authority, not the url — so a stale bookmark or a
 * forged id degrades to the ordinary new-child form instead of pre-filling
 * somebody else's details. A family with no children on file always gets the
 * new-child form, leaving first-time signup exactly as it was.
 */
export function initialChildSelection(
  children: readonly ExistingChild[],
  preselectedStudentId: string | null,
): string {
  if (!preselectedStudentId) return NEW_CHILD_SELECTION;
  return children.some((child) => child.student_id === preselectedStudentId)
    ? preselectedStudentId
    : NEW_CHILD_SELECTION;
}

/**
 * Copy an existing child's record onto the child step.
 *
 * The point is the NAME and DATE OF BIRTH: `PatchApplication` re-binds an
 * application to an existing student by (parent, full name, date of birth),
 * so reproducing them exactly is what stops a returning family from getting a
 * second student record. Everything else is convenience — pre-filled so the
 * family is not asked twice.
 *
 * `skill_level` is preserved from the draft because the student record does
 * not carry one; every other field is overwritten, blank included, so
 * switching between children never leaves the previous child's answers behind.
 */
export function childProfileFromExistingChild<T extends ChildProfileDraft>(
  child: ExistingChild,
  current: T,
): T {
  const [firstName, ...rest] = child.full_name.trim().split(/\s+/);
  return {
    ...current,
    first_name: firstName ?? "",
    last_name: rest.join(" "),
    date_of_birth: child.date_of_birth ?? "",
    emergency_contact_name: child.emergency_contact_name ?? "",
    emergency_contact_phone: child.emergency_contact_phone ?? "",
    medical_notes: child.no_medical_conditions
      ? NO_MEDICAL_CONDITIONS_SENTINEL
      : (child.medical_notes ?? ""),
  };
}
