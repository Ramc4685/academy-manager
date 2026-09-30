/**
 * Pure rules behind the one class form (class-page redesign, PR A).
 *
 * Create, Edit from the Sessions list and Edit on the class page share one
 * form. Everything that decides WHAT gets sent lives here so it can be unit
 * tested without a DOM: the price picker, the edit payload, the "why" box and
 * the optional welcome-email fields at create.
 *
 * Money rules this file pins:
 * - The class fee (`amount_cents`) stays the one number billing reads. A plan
 *   pick only fills that fee with the plan's current price, then links the
 *   class through the Pricing page's existing endpoint.
 * - An edit that does not change the price sends no `amount_cents` (or, for an
 *   unpriced class, its unchanged null so the percent-pay guard still runs),
 *   so it can never write a fee or a `session_fee_changed` audit row.
 * - An edit never sends the welcome-email (communication pack) fields: the
 *   PATCH is `exclude_unset`, so leaving them out keeps the stored values.
 */
import type {
  AdminSessionView,
  CreateSessionRequest,
  EditSessionRequest,
} from "@/lib/api/admin";
import type { PricingClass, PricingPlan } from "@/lib/api/v2/pricing";

/** The price-picker value for "no plan, type the fee". */
export const CUSTOM_PRICE = "custom";

/** "$60" for whole dollars, "$62.50" otherwise. */
export function formatFee(cents: number): string {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: cents % 100 === 0 ? 0 : 2,
    maximumFractionDigits: cents % 100 === 0 ? 0 : 2,
  }).format(cents / 100);
}

/** Plans a class may be put on: active ones only (the link refuses archived). */
export function pickablePlans(plans: readonly PricingPlan[] | undefined): PricingPlan[] {
  return (plans ?? []).filter((plan) => plan.is_active);
}

/** "Group class · $60 / month". */
export function planOptionLabel(plan: PricingPlan): string {
  const unit = plan.plan_type === "per_session" ? "session" : "month";
  return `${plan.name} · ${formatFee(plan.price_cents)} / ${unit}`;
}

/**
 * Where the picker starts: the class's current plan link, or Custom.
 *
 * The overview already drops a stale link (plan archived, or its price no
 * longer equals the fee), so a class whose fee matches no plan reads Custom.
 */
export function initialPriceChoice(
  classRow: Pick<PricingClass, "plan_id"> | undefined,
  plans: readonly PricingPlan[] | undefined,
): string {
  const planId = classRow?.plan_id ?? null;
  if (planId && pickablePlans(plans).some((plan) => plan.plan_id === planId)) return planId;
  return CUSTOM_PRICE;
}

/** The fee the form will save for a choice: the plan's price, or the typed fee. */
export function feeForChoice(
  choice: string,
  plans: readonly PricingPlan[] | undefined,
  customCents: number | null,
): number | null {
  if (choice === CUSTOM_PRICE) return customCents;
  const plan = pickablePlans(plans).find((p) => p.plan_id === choice);
  return plan ? plan.price_cents : customCents;
}

/** True when saving would change what the class is charged. */
export function priceChanges(
  previousCents: number | null | undefined,
  nextCents: number | null | undefined,
): boolean {
  return (previousCents ?? null) !== (nextCents ?? null);
}

/**
 * The plan link to write after the class is saved, or `undefined` for none.
 * `null` means "mark it custom" (unlink).
 */
export function planLinkToWrite(
  initialChoice: string,
  choice: string,
): string | null | undefined {
  if (choice === initialChoice) return undefined;
  return choice === CUSTOM_PRICE ? null : choice;
}

// ------------------------------------------------------------------ edit

/** Every value the class form edits. `amount_cents` is the resolved fee. */
export interface ClassFormValues {
  coach_id: string;
  title: string;
  location: string;
  days_of_week: string[];
  start_time: string;
  end_time: string;
  timezone: string | null;
  capacity: number;
  amount_cents: number | null;
  reason: string;
}

/** Seed the edit form from the stored class. */
export function classFormFromSession(session: AdminSessionView): ClassFormValues {
  return {
    coach_id: session.coach_id ?? "",
    title: session.title ?? "",
    location: session.location ?? "",
    days_of_week: [...(session.days_of_week ?? [])],
    start_time: session.start_time ?? "",
    end_time: session.end_time ?? "",
    timezone: session.timezone ?? null,
    capacity: session.capacity,
    amount_cents: session.amount_cents ?? null,
    reason: "",
  };
}

function isRecurring(session: AdminSessionView): boolean {
  return Boolean(session.days_of_week?.length && session.start_time && session.end_time);
}

/**
 * The PATCH body for an edit.
 *
 * Never carries a communication-pack field (the Welcome email tab owns those)
 * and carries `amount_cents` + `reason` only when an owner changes the price
 * (plus the unchanged null fee of an unpriced class, for the percent-pay guard).
 */
export function buildClassEditPayload(params: {
  session: AdminSessionView;
  values: ClassFormValues;
  isOwner: boolean;
}): EditSessionRequest {
  const { session, values, isOwner } = params;
  const payload: EditSessionRequest = {
    coach_id: values.coach_id,
    title: values.title,
    location: values.location,
    capacity: values.capacity,
    timezone: values.timezone ?? session.timezone ?? null,
  };
  if (isRecurring(session)) {
    payload.days_of_week = [...values.days_of_week];
    payload.start_time = values.start_time || null;
    payload.end_time = values.end_time || null;
  } else {
    // A one-off date is shown read-only; send it back unchanged, as before.
    payload.start_at = session.start_at;
    payload.end_at = session.end_at;
    payload.days_of_week = [];
    payload.start_time = null;
    payload.end_time = null;
  }
  if (isOwner && priceChanges(session.amount_cents, values.amount_cents)) {
    payload.amount_cents = values.amount_cents;
    const reason = values.reason.trim();
    if (reason) payload.reason = reason;
  } else if (session.amount_cents == null) {
    // An unpriced class sends its (unchanged) null fee back, as the old edit
    // dialogs did: the backend's percent-pay guard only runs when a null fee
    // is sent, so a switch to a percent-of-revenue coach is still refused.
    // Unchanged, it is not a price change: no owner gate, no audit row.
    payload.amount_cents = null;
  }
  return payload;
}

// ------------------------------------------------------ welcome email (create)

/** The optional welcome-email fields at Create, as typed (blank = default). */
export interface WelcomeEmailValues {
  whatsapp_group_link: string;
  venue_address: string;
  parking_notes: string;
  what_to_bring: string;
  arrival_minutes_before: string;
  coach_contact_policy: string;
  absence_policy: string;
}

export const EMPTY_WELCOME_EMAIL: WelcomeEmailValues = {
  whatsapp_group_link: "",
  venue_address: "",
  parking_notes: "",
  what_to_bring: "",
  arrival_minutes_before: "",
  coach_contact_policy: "",
  absence_policy: "",
};

type WelcomeEmailPayload = Pick<
  CreateSessionRequest,
  | "whatsapp_group_link"
  | "venue_address"
  | "parking_notes"
  | "what_to_bring"
  | "arrival_minutes_before"
  | "coach_contact_policy"
  | "absence_policy"
>;

/**
 * Only the fields the admin typed. A blank field is left out so the class
 * keeps inheriting the academy default (Settings) when the email is sent.
 */
export function welcomeEmailPayload(values: WelcomeEmailValues): WelcomeEmailPayload {
  const out: WelcomeEmailPayload = {};
  const textKeys = [
    "whatsapp_group_link",
    "venue_address",
    "parking_notes",
    "what_to_bring",
    "coach_contact_policy",
    "absence_policy",
  ] as const;
  for (const key of textKeys) {
    const value = values[key].trim();
    if (value) out[key] = value;
  }
  const minutes = values.arrival_minutes_before.trim();
  if (minutes !== "") {
    const parsed = Number.parseInt(minutes, 10);
    if (Number.isFinite(parsed)) out.arrival_minutes_before = Math.max(0, Math.min(120, parsed));
  }
  return out;
}

/** "Uses academy default: 123 Court St", or "" when the academy has none. */
export function academyDefaultPlaceholder(value: string | number | null | undefined): string {
  if (value == null) return "";
  const text = String(value).trim();
  return text ? `Uses academy default: ${text}` : "";
}

/** `18:00` + 45 minutes -> `18:45`; "" for unparseable input. */
export function addMinutesToTime(time: string, minutes: number): string {
  const [hourStr, minuteStr] = time.split(":");
  const hour = Number(hourStr);
  const minute = Number(minuteStr);
  if (!time || !Number.isFinite(hour) || !Number.isFinite(minute)) return "";
  const total = (hour * 60 + minute + minutes + 24 * 60) % (24 * 60);
  const nextHour = Math.floor(total / 60);
  const nextMinute = total % 60;
  return `${String(nextHour).padStart(2, "0")}:${String(nextMinute).padStart(2, "0")}`;
}

/** `"60"` -> 6000; `""` or invalid -> null. */
export function dollarsToCents(value: string): number | null {
  if (value.trim() === "") return null;
  const parsed = Number(value);
  if (!Number.isFinite(parsed) || parsed < 0) return null;
  return Math.round(parsed * 100);
}

/** 6000 -> `"60"`; 6250 -> `"62.50"`; null -> `""`. */
export function centsToDollars(cents: number | null | undefined): string {
  if (cents == null) return "";
  return cents % 100 === 0 ? String(cents / 100) : (cents / 100).toFixed(2);
}
