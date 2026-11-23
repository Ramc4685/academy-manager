/**
 * View model for Settings → Self-service (the parent self-service policy).
 *
 * Kept free of React and path aliases so `self-service-policy-form.node-test.mjs`
 * can load it directly.
 *
 * Money audit 2026-09-25:
 * - X5: the panel used to PUT all six fields. The cancellation fee and notice
 *   are also edited in Billing rules, so a stale copy here could revert the
 *   owner's change. Only fields that differ from the loaded policy are sent.
 * - X20: a cleared number box used to save 0. A makeup expiry of 0 rejects
 *   every makeup request, so a blank or out-of-range box is now an error.
 *
 * Settings overhaul Phase 1 PR 5: the cancellation fee and notice are edited
 * only in Billing rules (owner-only). This form no longer holds or sends
 * them; the BFF refuses a changed value from Self-service.
 *
 * Settings overhaul Phase 3 PR 10: "When a cancellation takes effect"
 * (cancellation_effective_timing) moved to Billing rules the same way, and
 * the panel it lives on was renamed Family policies. This form no longer
 * holds or sends it either.
 */

export type CancellationTiming = "immediate" | "end_of_period";

export interface SelfServicePolicy {
  absence_notice_min_hours: number;
  makeup_expiry_days: number;
  makeup_requires_notice: boolean;
  cancellation_minimum_notice_days: number;
  cancellation_fee_cents: number;
  cancellation_effective_timing: CancellationTiming;
  can_report_absence: boolean;
  can_request_makeup: boolean;
  can_request_pause: boolean;
  can_request_cancel: boolean;
  can_claim_waitlist_offer: boolean;
  //: Academy-level fallback for a class's welcome-email "Absences and
  //: make-ups" text; used only when the class leaves its own field empty.
  welcome_email_absence_policy_default: string;
  dropoff_checkin_enabled: boolean;
  dropoff_checkin_opens_minutes_before: number;
  dropoff_checkin_closes_minutes_after: number;
}

export type PolicyForm = {
  absence_notice_min_hours: string;
  makeup_expiry_days: string;
  makeup_requires_notice: boolean;
  can_report_absence: boolean;
  can_request_makeup: boolean;
  can_request_pause: boolean;
  can_request_cancel: boolean;
  can_claim_waitlist_offer: boolean;
  welcome_email_absence_policy_default: string;
  dropoff_checkin_enabled: boolean;
  dropoff_checkin_opens_minutes_before: string;
  dropoff_checkin_closes_minutes_after: string;
};

/** What Family policies may write: never the Billing rules cancellation terms. */
export type PolicyPatch = Partial<
  Omit<
    SelfServicePolicy,
    | "cancellation_minimum_notice_days"
    | "cancellation_fee_cents"
    | "cancellation_effective_timing"
  >
>;

/** Whole-number fields and the [min, max] each accepts (the server enforces the same). */
const WHOLE_NUMBER_BOUNDS = {
  absence_notice_min_hours: [0, Infinity],
  makeup_expiry_days: [1, Infinity],
  // Opens at most 60 min early so a confirmation always lands inside the
  // attendance marking window.
  dropoff_checkin_opens_minutes_before: [0, 60],
  dropoff_checkin_closes_minutes_after: [0, 240],
} as const;

export function policyToForm(data: SelfServicePolicy | null | undefined): PolicyForm {
  return {
    absence_notice_min_hours: data?.absence_notice_min_hours?.toString() ?? "",
    makeup_expiry_days: data?.makeup_expiry_days?.toString() ?? "",
    makeup_requires_notice: data?.makeup_requires_notice ?? false,
    can_report_absence: data?.can_report_absence ?? true,
    can_request_makeup: data?.can_request_makeup ?? true,
    can_request_pause: data?.can_request_pause ?? true,
    can_request_cancel: data?.can_request_cancel ?? true,
    can_claim_waitlist_offer: data?.can_claim_waitlist_offer ?? true,
    welcome_email_absence_policy_default: data?.welcome_email_absence_policy_default ?? "",
    dropoff_checkin_enabled: data?.dropoff_checkin_enabled ?? false,
    dropoff_checkin_opens_minutes_before: data?.dropoff_checkin_opens_minutes_before?.toString() ?? "",
    dropoff_checkin_closes_minutes_after: data?.dropoff_checkin_closes_minutes_after?.toString() ?? "",
  };
}

export function isPolicyDirty(original: PolicyForm, form: PolicyForm): boolean {
  return (Object.keys(form) as Array<keyof PolicyForm>).some((key) => form[key] !== original[key]);
}

function parseWholeNumber(raw: string, min: number, max: number): number | null {
  const trimmed = raw.trim();
  if (!/^\d+$/.test(trimmed)) return null;
  const value = Number(trimmed);
  return value >= min && value <= max ? value : null;
}

/**
 * The PUT body: only the fields whose value differs from `stored`, plus a
 * per-field message for anything that is not a valid value.
 */
export function policyPatch(
  stored: SelfServicePolicy | null | undefined,
  form: PolicyForm,
): { payload: PolicyPatch; errors: Record<string, string> } {
  const payload: PolicyPatch = {};
  const errors: Record<string, string> = {};

  for (const [key, [min, max]] of Object.entries(WHOLE_NUMBER_BOUNDS) as Array<
    [keyof typeof WHOLE_NUMBER_BOUNDS, readonly [number, number]]
  >) {
    // Untouched is never an error, even if the stored value is out of bounds
    // (e.g. a 0 saved by the old cleared-box bug): it must not lock Save.
    // A field an older response did not carry (undefined) left blank is untouched too.
    if (stored && form[key].trim() === String(stored[key] ?? "")) continue;
    const value = parseWholeNumber(form[key], min, max);
    if (value === null) {
      errors[key] =
        max === Infinity
          ? `Enter a whole number of at least ${min}.`
          : `Enter a whole number from ${min} to ${max}.`;
    } else if (value !== stored?.[key]) {
      payload[key] = value;
    }
  }

  if (form.dropoff_checkin_enabled !== (stored?.dropoff_checkin_enabled ?? false)) {
    payload.dropoff_checkin_enabled = form.dropoff_checkin_enabled;
  }
  if (form.makeup_requires_notice !== stored?.makeup_requires_notice) {
    payload.makeup_requires_notice = form.makeup_requires_notice;
  }
  for (const key of [
    "can_report_absence",
    "can_request_makeup",
    "can_request_pause",
    "can_request_cancel",
    "can_claim_waitlist_offer",
  ] as const) {
    if (form[key] !== (stored?.[key] ?? true)) {
      payload[key] = form[key];
    }
  }
  if (
    form.welcome_email_absence_policy_default !==
    (stored?.welcome_email_absence_policy_default ?? "")
  ) {
    payload.welcome_email_absence_policy_default = form.welcome_email_absence_policy_default;
  }
  return { payload, errors };
}

/** One line for the Family policies panel: the terms Billing rules sets. */
export function cancellationTermsSummary(
  data:
    | Pick<
        SelfServicePolicy,
        | "cancellation_minimum_notice_days"
        | "cancellation_fee_cents"
        | "cancellation_effective_timing"
      >
    | null
    | undefined,
): string {
  if (!data) return "Set in Billing rules.";
  const days = data.cancellation_minimum_notice_days;
  const notice = `${days} ${days === 1 ? "day" : "days"} notice`;
  const fee =
    data.cancellation_fee_cents > 0
      ? `$${(data.cancellation_fee_cents / 100).toFixed(2)} fee when notice is short`
      : "no fee";
  const timing =
    data.cancellation_effective_timing === "immediate"
      ? "takes effect immediately"
      : "takes effect at period end";
  return `${notice}, ${fee}, ${timing}. Set in Billing rules.`;
}
