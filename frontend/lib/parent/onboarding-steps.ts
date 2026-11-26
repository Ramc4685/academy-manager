import type { OnboardingApplication } from "@/lib/api/parent";

/** S21: which step the sign-up wizard opens on, and the step kept in the URL. */
export type OnboardingStep = "parent" | "child" | "waiver" | "session" | "review";

export const ONBOARDING_ORDER: OnboardingStep[] = ["parent", "child", "waiver", "session", "review"];
/**
 * When the academy assigns a waiver to a program, the right set of waivers is
 * only known once the family has chosen a class, so the class comes first.
 */
export const CLASS_FIRST_ORDER: OnboardingStep[] = ["parent", "child", "session", "waiver", "review"];

export function onboardingOrder(app: Pick<OnboardingApplication, "waiver_class_first">): OnboardingStep[] {
  return app.waiver_class_first ? CLASS_FIRST_ORDER : ONBOARDING_ORDER;
}

const filled = (value: string | null | undefined) => Boolean(value && value.trim());

function stepDone(step: OnboardingStep, app: OnboardingApplication): boolean {
  const p = app.parent_profile;
  const c = app.child_profile;
  switch (step) {
    case "parent":
      return filled(p.first_name) && filled(p.last_name) && filled(p.phone);
    case "child":
      return (
        filled(c.first_name) &&
        filled(c.last_name) &&
        filled(c.date_of_birth) &&
        filled(c.emergency_contact_name) &&
        filled(c.emergency_contact_phone)
      );
    case "waiver":
      return app.waiver_accepted;
    case "session":
      return Boolean(app.selected_session_id);
    case "review":
      return false;
  }
}

export function firstIncompleteStep(app: OnboardingApplication): OnboardingStep {
  const order = onboardingOrder(app);
  return order.find((step) => !stepDone(step, app)) ?? "review";
}

/**
 * The step to open: the one in the URL when every step before it is done
 * (a reload stays put), otherwise the first step still to fill in.
 */
export function resumeStep(app: OnboardingApplication, requested: string | null): OnboardingStep {
  const order = onboardingOrder(app);
  const first = firstIncompleteStep(app);
  const wanted = order.find((step) => step === requested);
  if (!wanted) return first;
  return order.indexOf(wanted) <= order.indexOf(first) ? wanted : first;
}

/** The query string with the application and step set, other params kept. */
export function onboardingSearch(search: string, applicationId: string, step: OnboardingStep): string {
  const params = new URLSearchParams(search);
  params.set("application", applicationId);
  params.set("step", step);
  return `?${params.toString()}`;
}
