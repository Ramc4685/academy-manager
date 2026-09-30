"use client";

/**
 * The one class form (class-page redesign, PR A).
 *
 * Create (Sessions list), Edit (Sessions list) and Edit (class page) all
 * render `ClassFormFields`. The welcome-email (communication pack) fields
 * left the Edit dialog: the class page's Welcome email tab edits them with
 * its own save. Create keeps them as an optional, collapsed last step.
 *
 * Price is a plan picker: every active Pricing plan, or "Custom price" with
 * the monthly fee box. Picking a plan fills the class fee with the plan's
 * price (the number billing reads, unchanged) and links the class to the
 * plan through the Pricing page's endpoint. Owner only: the plan list 403s
 * for a plain admin, so a non-owner never asks for it and sees the fee
 * read-only.
 */

import { useEffect, useRef, useState, type ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  createAdminSession,
  getAdminAcademy,
  getSelfServicePolicy,
  listAdminUsers,
  updateAdminSession,
  type AdminSessionView,
  type AdminUserView,
  type CreateSessionRequest,
} from "@/lib/api/admin";
import {
  formatBillingMonth,
  getPricingOverview,
  listScheduledClassFees,
  setClassPlan,
  type PricingPlan,
  type ScheduledClassFee,
} from "@/lib/api/v2/pricing";
import { queryKeys } from "@/lib/query/keys";
import { parseAcademyInstant, resolveAcademyTimeZone } from "@/lib/format/academy-time";

import { Button } from "@/components/ds/button";
import {
  DialogActions,
  DialogError,
  Field,
  RallyModal,
} from "@/components/ds/dialog-chrome";
import { OwnerOnlyFieldNote, useIsOwner } from "@/components/admin/owner-context";

import {
  CUSTOM_PRICE,
  EMPTY_WELCOME_EMAIL,
  academyDefaultPlaceholder,
  addMinutesToTime,
  centsToDollars,
  classFormFromSession,
  dollarsToCents,
  feeForChoice,
  formatFee,
  initialPriceChoice,
  pickablePlans,
  planOptionLabel,
  priceChanges,
  welcomeEmailPayload,
  type ClassFormValues,
  type WelcomeEmailValues,
} from "./class-form-logic";
import { shouldAdoptAcademyCapacity } from "./capacity-seed";
import { saveClassCreate, saveClassEdit } from "./class-form-save";

const inputClass =
  "w-full rounded-md border border-rally-line bg-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-rally-cobalt-600/30";
const lockedInputClass =
  "disabled:cursor-not-allowed disabled:bg-neutral-100 disabled:text-rally-muted";

const DAYS_OF_WEEK = [
  { value: "Mon", label: "Monday" },
  { value: "Tue", label: "Tuesday" },
  { value: "Wed", label: "Wednesday" },
  { value: "Thu", label: "Thursday" },
  { value: "Fri", label: "Friday" },
  { value: "Sat", label: "Saturday" },
  { value: "Sun", label: "Sunday" },
] as const;

// ------------------------------------------------------------------ fields

export interface PriceFieldProps {
  isOwner: boolean;
  /** Active plans (owner only); empty while loading or when none exist. */
  plans: PricingPlan[];
  /** Plans are still loading: the picker waits so a link is never misread. */
  plansLoading: boolean;
  choice: string;
  onChoiceChange: (choice: string) => void;
  customFee: string;
  onCustomFeeChange: (value: string) => void;
  /** The fee the class has today (edit) or null (create). */
  currentCents: number | null;
  /** A plan price change scheduled for this class ("Scheduled: $X from ..."). */
  scheduledFee?: Pick<ScheduledClassFee, "new_cents" | "effective_period">;
  /** Show the "Why is the price changing?" box. */
  showReason: boolean;
  reason: string;
  onReasonChange: (value: string) => void;
}

export interface ClassFormFieldsProps {
  mode: "create" | "edit";
  values: ClassFormValues;
  onChange: <K extends keyof ClassFormValues>(key: K, value: ClassFormValues[K]) => void;
  coaches: AdminUserView[];
  coachesLoading: boolean;
  /** Edit of a one-off class: the date is read-only and times are locked. */
  oneOffDateLabel?: string | null;
  /** Create only: the hint under the timezone box. */
  timezoneHint?: string;
  price: PriceFieldProps;
  /** Rendered after the price (Create's welcome-email step). */
  footer?: ReactNode;
}

export function ClassFormFields({
  mode,
  values,
  onChange,
  coaches,
  coachesLoading,
  oneOffDateLabel,
  timezoneHint,
  price,
  footer,
}: ClassFormFieldsProps) {
  const creating = mode === "create";
  const oneOff = !creating && oneOffDateLabel != null;
  const days = values.days_of_week;
  return (
    <>
      <Field label="Coach" required={creating}>
        {coaches.length > 0 ? (
          <select
            required
            value={values.coach_id}
            onChange={(event) => onChange("coach_id", event.target.value)}
            className={inputClass}
          >
            <option value="">Select coach</option>
            {coaches.map((coach) => (
              <option key={coach.user_id} value={coach.user_id}>
                {coach.display_name} ({coach.email})
              </option>
            ))}
          </select>
        ) : (
          <input
            type="text"
            required={creating}
            value={values.coach_id}
            onChange={(event) => onChange("coach_id", event.target.value)}
            className={inputClass}
            placeholder={coachesLoading ? "Loading coaches…" : "Coach reference"}
          />
        )}
      </Field>
      <Field label="Name" required={creating}>
        <input
          type="text"
          required={creating}
          value={values.title}
          onChange={(event) => onChange("title", event.target.value)}
          className={inputClass}
        />
      </Field>
      <Field label="Location" required={creating}>
        <input
          type="text"
          required={creating}
          value={values.location}
          onChange={(event) => onChange("location", event.target.value)}
          className={inputClass}
        />
      </Field>
      <div className="grid grid-cols-2 gap-3">
        <Field label={oneOff ? "Date" : "Day of week"} required={creating}>
          {oneOff ? (
            <input value={oneOffDateLabel ?? ""} readOnly className={inputClass} />
          ) : days.length > 1 ? (
            <input value={days.join(", ")} readOnly className={inputClass} />
          ) : (
            <select
              required
              value={days[0] ?? ""}
              onChange={(event) => onChange("days_of_week", [event.target.value])}
              className={inputClass}
            >
              {!days[0] && (
                <option value="" disabled>
                  Select a day…
                </option>
              )}
              {DAYS_OF_WEEK.map((day) => (
                <option key={day.value} value={day.value}>
                  {day.label}
                </option>
              ))}
            </select>
          )}
        </Field>
        <Field label="Start time" required={creating}>
          <input
            type="time"
            required={creating}
            value={values.start_time}
            onChange={(event) => onChange("start_time", event.target.value)}
            className={inputClass}
            disabled={oneOff}
          />
        </Field>
      </div>
      <div className="grid grid-cols-2 gap-3">
        <Field label="End time" required={creating}>
          <input
            type="time"
            required={creating}
            value={values.end_time}
            onChange={(event) => onChange("end_time", event.target.value)}
            className={inputClass}
            disabled={oneOff}
          />
        </Field>
        <Field label="Capacity" required={creating}>
          <input
            type="number"
            required={creating}
            min={1}
            value={values.capacity}
            onChange={(event) =>
              onChange("capacity", Number.parseInt(event.target.value, 10) || 1)
            }
            className={inputClass}
          />
        </Field>
      </div>
      {creating && (
        // Visible and editable: the times above are wall-clock times in THIS
        // zone, and billing and payroll re-derive every date from it.
        <Field label="Timezone" required>
          <input
            type="text"
            required
            value={values.timezone ?? ""}
            onChange={(event) => onChange("timezone", event.target.value)}
            className={inputClass}
            aria-describedby="create-session-tz-hint"
            data-testid="create-session-timezone"
          />
          {timezoneHint && (
            <p id="create-session-tz-hint" className="mt-1 text-xs text-rally-muted">
              {timezoneHint}
            </p>
          )}
        </Field>
      )}
      <PriceField mode={mode} {...price} />
      {footer}
    </>
  );
}

function PriceField({
  mode,
  isOwner,
  plans,
  plansLoading,
  choice,
  onChoiceChange,
  customFee,
  onCustomFeeChange,
  currentCents,
  scheduledFee,
  showReason,
  reason,
  onReasonChange,
}: PriceFieldProps & { mode: "create" | "edit" }) {
  const creating = mode === "create";
  const scheduledNote = scheduledFee ? (
    <p className="text-xs text-status-amber-800" data-testid="session-edit-scheduled-fee">
      Scheduled: {formatFee(scheduledFee.new_cents)} from{" "}
      {formatBillingMonth(scheduledFee.effective_period, { year: true })} (plan price change on
      Pricing).
    </p>
  ) : null;

  if (!isOwner) {
    // The plan list is owner-only (403 for an admin), so an admin sees the
    // fee as text. At create the class starts unpriced; the owner prices it.
    return (
      <div>
        <span className="mb-1 block font-mono text-[10px] font-bold uppercase tracking-overline text-rally-muted">
          Price
        </span>
        <p className="text-sm text-rally-ink" data-testid="class-form-price-readonly">
          {currentCents == null ? "Not set" : `${formatFee(currentCents)}/month`}
        </p>
        {scheduledNote}
        <OwnerOnlyFieldNote className="mt-1" />
      </div>
    );
  }

  const custom = choice === CUSTOM_PRICE;
  const feeTestId = creating ? "create-session-monthly-fee" : "session-edit-monthly-fee";
  return (
    <>
      <Field label="Price" required={creating}>
        <select
          value={choice}
          onChange={(event) => onChoiceChange(event.target.value)}
          disabled={plansLoading}
          className={`${inputClass} ${lockedInputClass}`}
          data-testid="class-form-price"
        >
          {plans.map((plan) => (
            <option key={plan.plan_id} value={plan.plan_id}>
              {planOptionLabel(plan)}
            </option>
          ))}
          <option value={CUSTOM_PRICE}>Custom price</option>
        </select>
      </Field>
      {plansLoading && <p className="text-xs text-rally-muted">Loading plans…</p>}
      {custom && (
        <Field label="Monthly fee" required={creating}>
          <input
            type="number"
            required={creating}
            min={0}
            step="0.01"
            value={customFee}
            disabled={plansLoading}
            data-testid={feeTestId}
            onChange={(event) => onCustomFeeChange(event.target.value)}
            className={`${inputClass} ${lockedInputClass}`}
          />
        </Field>
      )}
      {custom && (
        <p className="-mt-2 text-xs text-rally-muted">
          Percent-paid coaches need a price for payroll. Enter 0 for a free class.
        </p>
      )}
      {scheduledNote}
      {showReason && (
        <Field label="Why is the price changing?">
          <input
            value={reason}
            onChange={(event) => onReasonChange(event.target.value)}
            className={inputClass}
            placeholder="Optional"
            maxLength={500}
            data-testid="class-form-reason"
          />
        </Field>
      )}
    </>
  );
}

// ------------------------------------------------------ welcome email (create)

export interface WelcomeEmailDefaults {
  venue_address?: string | null;
  parking_notes?: string | null;
  what_to_bring?: string | null;
  arrival_minutes_before?: number | null;
  absence_policy?: string | null;
}

/**
 * Create's optional "Welcome email" step. Every box starts blank; a blank box
 * sends nothing, so the class keeps using the academy default shown as the
 * placeholder (Settings › Academy profile › Class defaults, Family policies).
 */
export function WelcomeEmailFields({
  values,
  onChange,
  defaults,
  defaultOpen = false,
}: {
  values: WelcomeEmailValues;
  onChange: (key: keyof WelcomeEmailValues, value: string) => void;
  defaults: WelcomeEmailDefaults;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const arrivalDefault =
    defaults.arrival_minutes_before != null
      ? `${defaults.arrival_minutes_before} minutes`
      : null;
  const text = (
    key: Exclude<keyof WelcomeEmailValues, "arrival_minutes_before">,
    label: string,
    placeholder: string,
    rows = 2,
  ) => (
    <Field label={label}>
      <textarea
        rows={rows}
        value={values[key]}
        onChange={(event) => onChange(key, event.target.value)}
        className={inputClass}
        placeholder={placeholder}
      />
    </Field>
  );
  return (
    <div className="rounded-md border border-rally-line" data-testid="class-form-welcome-email">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        className="flex min-h-touch w-full items-center justify-between px-3 py-2 text-left text-sm font-medium text-rally-ink"
      >
        <span>Welcome email (optional)</span>
        <span aria-hidden className="text-rally-muted">
          {open ? "−" : "+"}
        </span>
      </button>
      {open ? (
        <div className="space-y-3 border-t border-rally-line px-3 py-3">
          <p className="text-xs text-rally-muted">
            Emailed to a family when they join. Leave a box blank to use the academy default.
          </p>
          <Field label="WhatsApp group link">
            <input
              type="url"
              inputMode="url"
              value={values.whatsapp_group_link}
              onChange={(event) => onChange("whatsapp_group_link", event.target.value)}
              className={inputClass}
              placeholder="https://chat.whatsapp.com/..."
            />
          </Field>
          {text("venue_address", "Venue address", academyDefaultPlaceholder(defaults.venue_address))}
          {text("parking_notes", "Parking notes", academyDefaultPlaceholder(defaults.parking_notes))}
          {text("what_to_bring", "What to bring", academyDefaultPlaceholder(defaults.what_to_bring))}
          <Field label="Arrive N minutes before class">
            <input
              type="number"
              min={0}
              max={120}
              value={values.arrival_minutes_before}
              onChange={(event) => onChange("arrival_minutes_before", event.target.value)}
              className={inputClass}
              placeholder={academyDefaultPlaceholder(arrivalDefault)}
            />
          </Field>
          {text("coach_contact_policy", "Coach contact", "")}
          {text(
            "absence_policy",
            "Absence & make-up policy",
            academyDefaultPlaceholder(defaults.absence_policy),
            3,
          )}
        </div>
      ) : null}
    </div>
  );
}

// ------------------------------------------------------------------ dialogs

function errorMessage(err: unknown, fallback: string): string {
  const message = err instanceof Error ? err.message.trim() : "";
  return message || fallback;
}

/** Owner-only plan list + this academy's class links (one read, shared cache). */
function usePricing(enabled: boolean) {
  return useQuery({
    queryKey: queryKeys.admin.pricing(),
    queryFn: getPricingOverview,
    enabled,
    retry: false,
  });
}

function useCoaches(enabled: boolean) {
  const query = useQuery({
    queryKey: queryKeys.admin.users("coach"),
    queryFn: () => listAdminUsers("coach"),
    enabled,
  });
  return { coaches: query.data?.users ?? [], loading: query.isLoading };
}

function invalidatePricing(queryClient: ReturnType<typeof useQueryClient>) {
  void queryClient.invalidateQueries({ queryKey: queryKeys.admin.pricing() });
  void queryClient.invalidateQueries({ queryKey: queryKeys.admin.scheduledClassFees() });
}

export function EditClassDialog({
  open,
  session,
  onOpenChange,
  onSaved,
}: {
  open: boolean;
  session: AdminSessionView | null;
  onOpenChange: (open: boolean) => void;
  onSaved: (session: AdminSessionView) => void;
}) {
  const isOwner = useIsOwner();
  const queryClient = useQueryClient();
  const [values, setValues] = useState<ClassFormValues | null>(null);
  // The class as last saved by this dialog when it stays open after a
  // partial save (fee written, plan link failed). Until the parent passes a
  // fresh `session`, it is the baseline "what is stored" for the next save.
  const [savedBaseline, setSavedBaseline] = useState<AdminSessionView | null>(null);
  const [touchedChoice, setTouchedChoice] = useState<string | null>(null);
  const [customFee, setCustomFee] = useState("");
  const [error, setError] = useState<string | null>(null);
  const { coaches, loading: coachesLoading } = useCoaches(open);
  const pricingQuery = usePricing(open && isOwner);
  // "Scheduled: $X from <Month>" (Settings overhaul PR 26): readable by any
  // admin; a failed read just hides the note.
  const scheduledFeesQuery = useQuery({
    queryKey: queryKeys.admin.scheduledClassFees(),
    queryFn: listScheduledClassFees,
    enabled: open,
    retry: false,
  });

  // Seed on open (or when a different class is opened), not on every refetch
  // of the same class, so a background refetch never wipes the admin's edits
  // or a partial-save error.
  const seededFor = useRef<string | null>(null);
  useEffect(() => {
    if (!open || !session) {
      seededFor.current = null;
      return;
    }
    if (seededFor.current === session.session_id) return;
    seededFor.current = session.session_id;
    setValues(classFormFromSession(session));
    setSavedBaseline(null);
    setTouchedChoice(null);
    setCustomFee(centsToDollars(session.amount_cents));
    setError(null);
  }, [open, session]);
  const stored =
    savedBaseline && session && savedBaseline.session_id === session.session_id
      ? savedBaseline
      : session;

  const plans = pickablePlans(pricingQuery.data?.plans);
  const plansLoading = isOwner && pricingQuery.isLoading;
  const classRow = stored
    ? pricingQuery.data?.classes.find((row) => row.session_id === stored.session_id)
    : undefined;
  // Until the overview is read, the link is unknown: start at Custom and
  // write no link change (the picker is disabled meanwhile).
  const initialChoice = pricingQuery.data
    ? initialPriceChoice(classRow, pricingQuery.data.plans)
    : CUSTOM_PRICE;
  const choice = touchedChoice ?? initialChoice;
  const currentCents = stored?.amount_cents ?? null;
  const nextCents = isOwner
    ? feeForChoice(choice, plans, dollarsToCents(customFee))
    : currentCents;
  const showReason = isOwner && priceChanges(currentCents, nextCents);
  const scheduledFee = session
    ? (scheduledFeesQuery.data ?? []).find((row) => row.session_id === session.session_id)
    : undefined;

  const mutation = useMutation({
    mutationFn: async () => {
      if (!stored || !values) throw new Error("No class selected.");
      // Fee first, then the link: the link endpoint refuses a plan whose
      // price is not the class fee (409).
      return saveClassEdit(
        {
          session: stored,
          values: { ...values, amount_cents: nextCents },
          isOwner,
          pricingLoaded: Boolean(pricingQuery.data),
          initialChoice,
          choice,
        },
        { updateSession: updateAdminSession, setClassPlan },
      );
    },
    onSuccess: ({ saved, pricingTouched, linkError }) => {
      if (pricingTouched) invalidatePricing(queryClient);
      if (linkError) {
        // The class (and its fee) saved but the link did not: stay open on
        // the saved class so the next save compares against what is stored.
        setSavedBaseline(saved);
        setError(linkError);
        void queryClient.invalidateQueries({
          queryKey: queryKeys.admin.sessionDetail(saved.session_id),
        });
        void queryClient.invalidateQueries({ queryKey: queryKeys.admin.sessions("upcoming") });
        return;
      }
      setError(null);
      onSaved(saved);
    },
    onError: (err: unknown) => setError(errorMessage(err, "Failed to update session.")),
  });

  const onChange = <K extends keyof ClassFormValues>(key: K, value: ClassFormValues[K]) =>
    setValues((current) => (current ? { ...current, [key]: value } : current));

  const oneOffDateLabel =
    session && !(session.days_of_week?.length && session.start_time && session.end_time)
      ? parseAcademyInstant(session.start_at).toLocaleDateString("en-US", {
          month: "short",
          day: "numeric",
          year: "numeric",
          timeZone: resolveAcademyTimeZone(session.timezone).timeZone,
        })
      : null;

  return (
    <RallyModal
      open={open}
      onOpenChange={(nextOpen) => {
        if (!nextOpen) setError(null);
        onOpenChange(nextOpen);
      }}
      title="Edit session"
      description="Coach, schedule, seats and price."
      overline="Session"
    >
      {error && <DialogError message={error} />}
      {values && (
        <form
          className="space-y-3"
          onSubmit={(event) => {
            event.preventDefault();
            mutation.mutate();
          }}
        >
          <ClassFormFields
            mode="edit"
            values={values}
            onChange={onChange}
            coaches={coaches}
            coachesLoading={coachesLoading}
            oneOffDateLabel={oneOffDateLabel}
            price={{
              isOwner,
              plans,
              plansLoading,
              choice,
              onChoiceChange: setTouchedChoice,
              customFee,
              onCustomFeeChange: setCustomFee,
              currentCents,
              scheduledFee,
              showReason,
              reason: values.reason,
              onReasonChange: (reason) => onChange("reason", reason),
            }}
          />
          <DialogActions>
            <Button variant="secondary" size="sm" type="button" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button
              variant="primary"
              size="sm"
              type="submit"
              disabled={mutation.isPending || plansLoading}
            >
              {mutation.isPending ? "Saving..." : "Save"}
            </Button>
          </DialogActions>
        </form>
      )}
    </RallyModal>
  );
}

// Settings overhaul Phase 3 PR 9: no BLNO-specific weekday/time default; the
// capacity and class length come from the academy's Class defaults.
const EMPTY_CREATE: ClassFormValues = {
  coach_id: "",
  title: "",
  location: "",
  days_of_week: [],
  start_time: "",
  end_time: "",
  timezone: null,
  capacity: 10,
  amount_cents: null,
  reason: "",
};

/**
 * Seed for the create form's timezone: never guess UTC (a 6:00 PM Chicago
 * class saved as UTC moves five hours for billing and payroll). Prefer the
 * academy's zone, then the admin's browser zone, shown and editable.
 */
function seedTimezone(academyTimezone: string | null | undefined): string {
  return resolveAcademyTimeZone(academyTimezone).timeZone;
}

export function CreateClassDialog({
  open,
  onOpenChange,
  onCreated,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** `warning` is set when the class was created but its plan link failed. */
  onCreated: (session: AdminSessionView, warning?: string) => void;
}) {
  const isOwner = useIsOwner();
  const queryClient = useQueryClient();
  const [values, setValues] = useState<ClassFormValues>(EMPTY_CREATE);
  const [choice, setChoice] = useState<string>(CUSTOM_PRICE);
  const [customFee, setCustomFee] = useState("");
  const [welcome, setWelcome] = useState<WelcomeEmailValues>(EMPTY_WELCOME_EMAIL);
  const [error, setError] = useState<string | null>(null);

  const academyQuery = useQuery({
    queryKey: queryKeys.admin.academy(),
    queryFn: getAdminAcademy,
    staleTime: 10 * 60 * 1000,
  });
  const policyQuery = useQuery({
    queryKey: queryKeys.admin.selfServicePolicy(),
    queryFn: getSelfServicePolicy,
    enabled: open,
    retry: false,
  });
  const { coaches, loading: coachesLoading } = useCoaches(open);
  const pricingQuery = usePricing(open && isOwner);
  const plans = pickablePlans(pricingQuery.data?.plans);

  const academy = academyQuery.data;
  const academyTimezone = academy?.timezone;
  const defaultCapacity = academy?.default_class_size ?? EMPTY_CREATE.capacity;
  const defaultClassLengthMinutes = academy?.default_class_length_minutes ?? 45;
  const wasOpen = useRef(false);

  // Issue #148: seed defaults on open; afterwards patch only the timezone and
  // capacity, and only while the admin has not touched them.
  const [timezoneTouched, setTimezoneTouched] = useState(false);
  const [endTimeTouched, setEndTimeTouched] = useState(false);
  const [capacityTouched, setCapacityTouched] = useState(false);
  useEffect(() => {
    if (open && !wasOpen.current) {
      setValues({
        ...EMPTY_CREATE,
        timezone: seedTimezone(academyTimezone),
        capacity: defaultCapacity,
      });
      setChoice(CUSTOM_PRICE);
      setCustomFee("");
      setWelcome(EMPTY_WELCOME_EMAIL);
      setTimezoneTouched(false);
      setEndTimeTouched(false);
      setCapacityTouched(false);
      setError(null);
    } else if (open && academyTimezone && !timezoneTouched) {
      setValues((current) => ({ ...current, timezone: academyTimezone }));
    }
    if (
      shouldAdoptAcademyCapacity({
        open,
        wasOpen: wasOpen.current,
        capacityTouched,
        defaultClassSize: academy?.default_class_size,
      })
    ) {
      setValues((current) => ({ ...current, capacity: defaultCapacity }));
    }
    wasOpen.current = open;
  }, [
    open,
    academyTimezone,
    timezoneTouched,
    defaultCapacity,
    capacityTouched,
    academy?.default_class_size,
  ]);

  const fee = isOwner ? feeForChoice(choice, plans, dollarsToCents(customFee)) : null;

  const mutation = useMutation({
    mutationFn: async () => {
      const payload: CreateSessionRequest = {
        coach_id: values.coach_id,
        title: values.title,
        location: values.location,
        days_of_week: values.days_of_week,
        start_time: values.start_time,
        end_time: values.end_time,
        timezone: values.timezone,
        capacity: values.capacity,
        // A non-owner never sends a fee: the BFF 403s any price from them.
        amount_cents: fee,
        ...welcomeEmailPayload(welcome),
      };
      // The class exists once created; a link failure comes back as a
      // warning (retrying Create would duplicate the class).
      return saveClassCreate(
        { payload, isOwner, choice, customChoice: CUSTOM_PRICE },
        { createSession: createAdminSession, setClassPlan },
      );
    },
    onSuccess: ({ created, warning, pricingTouched }) => {
      if (pricingTouched) invalidatePricing(queryClient);
      setError(null);
      onCreated(created, warning);
    },
    onError: (err: unknown) => setError(errorMessage(err, "Failed to create session.")),
  });

  const onChange = <K extends keyof ClassFormValues>(key: K, value: ClassFormValues[K]) => {
    if (key === "timezone") setTimezoneTouched(true);
    if (key === "capacity") setCapacityTouched(true);
    if (key === "end_time") setEndTimeTouched(true);
    setValues((current) => {
      const next = { ...current, [key]: value };
      // Class defaults: the end time follows the academy's class length
      // until the admin edits it directly.
      if (key === "start_time" && !endTimeTouched) {
        next.end_time = addMinutesToTime(String(value), defaultClassLengthMinutes);
      }
      return next;
    });
  };

  return (
    <RallyModal
      open={open}
      onOpenChange={onOpenChange}
      title="Create session"
      description="Create a weekly recurring session."
      overline="New session"
    >
      {error && <DialogError message={error} />}
      <form
        className="space-y-3"
        onSubmit={(event) => {
          event.preventDefault();
          setError(null);
          mutation.mutate();
        }}
      >
        <ClassFormFields
          mode="create"
          values={values}
          onChange={onChange}
          coaches={coaches}
          coachesLoading={coachesLoading}
          timezoneHint={
            academyTimezone
              ? "From your academy settings."
              : "Your academy has no timezone set — this defaulted to your browser's zone. Confirm it before saving."
          }
          price={{
            isOwner,
            plans,
            // Create starts at Custom and links only on an explicit pick, so
            // the picker never has to wait for the plan list.
            plansLoading: false,
            choice,
            onChoiceChange: setChoice,
            customFee,
            onCustomFeeChange: setCustomFee,
            currentCents: null,
            showReason: false,
            reason: "",
            onReasonChange: () => {},
          }}
          footer={
            <WelcomeEmailFields
              values={welcome}
              onChange={(key, value) => setWelcome((current) => ({ ...current, [key]: value }))}
              defaults={{
                venue_address: academy?.default_venue_address,
                parking_notes: academy?.default_parking_note,
                what_to_bring: academy?.default_what_to_bring,
                arrival_minutes_before: academy?.default_arrival_minutes_before,
                absence_policy: policyQuery.data?.welcome_email_absence_policy_default,
              }}
            />
          }
        />
        <DialogActions>
          <Button variant="secondary" size="sm" type="button" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button variant="primary" size="sm" type="submit" disabled={mutation.isPending}>
            {mutation.isPending ? "Creating…" : "Create"}
          </Button>
        </DialogActions>
      </form>
    </RallyModal>
  );
}
