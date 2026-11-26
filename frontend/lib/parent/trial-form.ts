/**
 * S17: the trial form says which field still blocks the button, instead of a
 * silently disabled submit.
 */
export interface TrialFormState {
  studentRef: "existing_student" | "prospective";
  studentId: string;
  prospectiveName: string;
  sessionId: string;
  preferredStart: string;
  preferredEnd: string;
}

/** The first missing required field, in form order, or null when complete. */
export function trialMissingField(form: TrialFormState): string | null {
  if (form.studentRef === "existing_student" ? !form.studentId : !form.prospectiveName.trim()) {
    return form.studentRef === "existing_student" ? "Choose a child." : "Add the child's name.";
  }
  if (!form.sessionId) return "Choose a class.";
  if (!form.preferredStart) return "Pick the first day that suits you.";
  if (!form.preferredEnd) return "Pick the last day that suits you.";
  if (form.preferredEnd < form.preferredStart) return "The last day must be on or after the first day.";
  return null;
}

export const TRIAL_SUCCESS = {
  title: "Trial requested",
  description: "The academy will confirm a date with you. You can follow it below.",
};
