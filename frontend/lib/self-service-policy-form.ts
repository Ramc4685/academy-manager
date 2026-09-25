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
 */

export type CancellationTiming = "immediate" | "end_of_period";

export interface SelfServicePolicy {
  absence_notice_min_hours: number;
  makeup_expiry_days: number;
  makeup_requires_notice: boolean;
  cancellation_minimum_notice_days: number;
  cancellation_fee_cents: number;
  cancellation_effective_timing: CancellationTiming;
}

export type PolicyForm = {
  absence_notice_min_hours: string;
  makeup_expiry_days: string;
  makeup_requires_notice: boolean;
  cancellation_minimum_notice_days: string;
  cancellation_fee_dollars: string;
  cancellation_effective_timing: CancellationTiming;
};

export type PolicyPatch = Partial<SelfServicePolicy>;

/** Whole-number fields and the smallest value each accepts. */
const WHOLE_NUMBER_MINIMUMS = {
  absence_notice_min_hours: 0,
  makeup_expiry_days: 1,
  cancellation_minimum_notice_days: 0,
} as const;

export function policyToForm(data: SelfServicePolicy | null | undefined): PolicyForm {
  return {
    absence_notice_min_hours: data?.absence_notice_min_hours?.toString() ?? "",
    makeup_expiry_days: data?.makeup_expiry_days?.toString() ?? "",
    makeup_requires_notice: data?.makeup_requires_notice ?? false,
    cancellation_minimum_notice_days: data?.cancellation_minimum_notice_days?.toString() ?? "",
    cancellation_fee_dollars:
      data?.cancellation_fee_cents === undefined || data?.cancellation_fee_cents === null
        ? ""
        : (data.cancellation_fee_cents / 100).toFixed(2),
    cancellation_effective_timing: data?.cancellation_effective_timing ?? "immediate",
  };
}

export function isPolicyDirty(original: PolicyForm, form: PolicyForm): boolean {
  return (Object.keys(form) as Array<keyof PolicyForm>).some((key) => form[key] !== original[key]);
}

function parseWholeNumber(raw: string, min: number): number | null {
  const trimmed = raw.trim();
  if (!/^\d+$/.test(trimmed)) return null;
  const value = Number(trimmed);
  return value >= min ? value : null;
}

function parseDollars(raw: string): number | null {
  const trimmed = raw.trim();
  if (!/^\d+(\.\d{1,2})?$/.test(trimmed)) return null;
  return Math.round(Number(trimmed) * 100);
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

  for (const [key, min] of Object.entries(WHOLE_NUMBER_MINIMUMS) as Array<
    [keyof typeof WHOLE_NUMBER_MINIMUMS, number]
  >) {
    // Untouched is never an error, even if the stored value is out of bounds
    // (e.g. a 0 saved by the old cleared-box bug): it must not lock Save.
    if (stored && form[key].trim() === String(stored[key])) continue;
    const value = parseWholeNumber(form[key], min);
    if (value === null) {
      errors[key] = `Enter a whole number of at least ${min}.`;
    } else if (value !== stored?.[key]) {
      payload[key] = value;
    }
  }

  const feeCents = parseDollars(form.cancellation_fee_dollars);
  if (feeCents === null) {
    errors.cancellation_fee_dollars = "Enter an amount like 25.00. Use 0 for no fee.";
  } else if (feeCents !== stored?.cancellation_fee_cents) {
    payload.cancellation_fee_cents = feeCents;
  }

  if (form.makeup_requires_notice !== stored?.makeup_requires_notice) {
    payload.makeup_requires_notice = form.makeup_requires_notice;
  }
  if (form.cancellation_effective_timing !== stored?.cancellation_effective_timing) {
    payload.cancellation_effective_timing = form.cancellation_effective_timing;
  }
  return { payload, errors };
}
