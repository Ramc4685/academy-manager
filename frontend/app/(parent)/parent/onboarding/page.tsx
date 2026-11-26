"use client";

import { useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import { WaiverSignBlock } from "@/components/parent/waiver-sign-block";
import { WaiverText } from "@/components/waivers/waiver-text";
import {
  hasAgePaths,
  initialsComplete,
  initialsNeeded,
  parseWaiverSections,
  signingPathFor,
} from "@/lib/waivers/sections";
import { Button } from "@/components/ds/button";

import {
  getParentAcademy,
  getParentProfile,
  getRegistrationWaiver,
  listAvailableParentSessions,
  patchOnboarding,
  quoteEnrollment,
  startCheckout,
  startOnboarding,
  type EnrollmentQuote,
  type OnboardingApplication,
  type ParentAvailableSession,
  type ParentSelfChild,
  type RegistrationWaiver,
} from "@/lib/api/parent";
import type { ApiError } from "@/lib/api/client";
import { toCheckoutStartMessage } from "@/lib/api/payment-error";
import {
  formatAcademyMoment,
  formatSessionOccurrence,
} from "@/lib/format/session-display";
import { queryKeys } from "@/lib/query/keys";
import { clearReferralCode, storedReferralCode } from "@/lib/referral-capture";
import {
  childProfileFromExistingChild,
  initialChildSelection,
  NEW_CHILD_SELECTION,
  NO_MEDICAL_CONDITIONS_SENTINEL,
  reEnrollChildId,
} from "@/lib/parent/re-enroll";
import {
  nextStep,
  onboardingOrder,
  onboardingSearch,
  resumeStep,
  type OnboardingStep,
} from "@/lib/parent/onboarding-steps";
import {
  classLevelNote,
  dateOfBirthError,
  localIsoDate,
  monthlyPriceLabel,
  reviewPriceLines,
  skillLevelLabel,
  SKILL_LEVEL_HINTS,
  waiverPerChildNote,
} from "@/lib/parent/onboarding-copy";
import { listPhrase } from "@/lib/parent/profile-gaps";

/**
 * Parent onboarding stepper.
 *
 * Steps: 1) parent info → 2) child info → 3) waiver → 4) select session → checkout.
 *
 * Autosaves on each step via PATCH; the application_id lives in URL state so
 * the parent can resume after a tab close.
 */

type Step = OnboardingStep;

/**
 * Server-side completeness guard (issue #380): checkout refuses an
 * application missing any of these. The wizard marks all of them `required`,
 * so the guard should only ever fire for an application drafted before those
 * fields existed. When it does, send the parent back to the step that owns
 * the field instead of stranding them on the review screen with a raw
 * machine-readable field name.
 */
const CHECKOUT_START_FAILED =
  "We couldn't start the payment. Please try again, or contact the academy.";

const MISSING_FIELD_HELP: Record<string, { step: Step; label: string }> = {
  parent_phone: { step: "parent", label: "your phone number" },
  date_of_birth: { step: "child", label: "your child's date of birth" },
  emergency_contact_name: { step: "child", label: "an emergency contact name" },
  emergency_contact_phone: { step: "child", label: "an emergency contact phone number" },
};

export default function OnboardingStepperPage() {
  const [app, setApp] = useState<OnboardingApplication | null>(null);
  const [step, setStep] = useState<Step>("parent");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const queryClient = useQueryClient();
  const sessionsQuery = useQuery({
    queryKey: ["parent", "sessions", "available"],
    queryFn: listAvailableParentSessions,
    staleTime: 60_000,
  });
  // Session times are UTC instants. Rendering them in the VIEWER's browser
  // timezone showed a 6:00 PM Chicago class as "1:00 PM" to the parent — the
  // wrong hour, on the screen where they commit to paying. Sessions carry
  // their own zone; the academy zone is the fallback when they do not.
  const academyQuery = useQuery({
    queryKey: ["parent", "academy"],
    queryFn: getParentAcademy,
    staleTime: 10 * 60 * 1000,
  });
  const academyTimezone = academyQuery.data?.timezone ?? null;
  // #827: the children this parent already has. A returning family must not
  // get a SECOND student record, and the binding the backend does is by name
  // and date of birth — so the child step offers these to copy forward rather
  // than asking the family to retype them and hoping they match.
  //
  // A first-time signup has none; the query 404s/empties harmlessly and the
  // step renders exactly as it did before.
  const profileQuery = useQuery({
    queryKey: queryKeys.parent.profile(),
    queryFn: getParentProfile,
    staleTime: 60_000,
    retry: false,
  });
  const existingChildren = profileQuery.data?.children ?? [];
  // Read once, from the url the departed row linked to. `useSearchParams`
  // would need its own Suspense boundary around this page; this needs no
  // reactivity — the pin is a one-shot hint for the first render.
  const [preselectedChildId] = useState<string | null>(() =>
    typeof window === "undefined" ? null : reEnrollChildId(window.location.search),
  );
  const selectedSessionId = app?.selected_session_id;
  const quoteQuery = useQuery({
    queryKey: ["parent", "enrollment-quote", selectedSessionId],
    queryFn: () => quoteEnrollment({ session_id: selectedSessionId as string }),
    enabled: Boolean(selectedSessionId),
    staleTime: 30_000,
  });

  useEffect(() => {
    void (async () => {
      try {
        // S02: "Finish registration" links here with the application to resume.
        const params = new URLSearchParams(window.location.search);
        const fresh = await startOnboarding(params.get("application"));
        setApp(fresh);
        // S21: a reload stays on its step; a new or second child skips what is already done.
        setStep(resumeStep(fresh, params.get("step")));
      } catch (e) {
        setError((e as Error).message);
      }
    })();
  }, []);

  const applicationId = app?.application_id;
  useEffect(() => {
    if (!applicationId) return;
    const search = onboardingSearch(window.location.search, applicationId, step);
    if (search !== window.location.search) window.history.replaceState(null, "", search);
  }, [applicationId, step]);

  if (error && !app) {
    return (
      <section data-testid="parent-onboarding" className="space-y-4">
        <OnboardingStyles />
        <div
          role="alert"
          className="rounded-xl border border-red-200 bg-red-50 p-3 text-sm text-red-800"
        >
          {error}
        </div>
      </section>
    );
  }

  if (!app) {
    return (
      <section data-testid="parent-onboarding" className="space-y-4">
        <OnboardingStyles />
        <div className="h-6 w-40 rounded shimmer" />
        <div className="space-y-3">
          <div className="h-11 rounded-xl shimmer" />
          <div className="h-11 rounded-xl shimmer" />
          <div className="h-11 rounded-xl shimmer" />
        </div>
      </section>
    );
  }

  async function save(patch: Parameters<typeof patchOnboarding>[1]): Promise<boolean> {
    if (!app) return false;
    setSaving(true);
    setError(null);
    try {
      const next = await patchOnboarding(app.application_id, patch);
      setApp(next);
      return true;
    } catch (e) {
      setError((e as Error).message);
      return false;
    } finally {
      setSaving(false);
    }
  }

  const order = onboardingOrder(app);

  function advance() {
    if (!app) return;
    const next = nextStep(app, step);
    if (next) setStep(next);
  }

  async function goToCheckout() {
    if (!app) return;
    const origin = window.location.origin;
    setSaving(true);
    setError(null);
    try {
      const { redirect_url } = await startCheckout({
        application_id: app.application_id,
        success_url: `${origin}/parent/checkout/return?application_id=${app.application_id}`,
        cancel_url: `${origin}/parent/onboarding`,
        // Charge the quote this screen actually showed, not a re-quote taken
        // at click time — the two legitimately disagree once a class crosses
        // the two-hour cutoff or a date is cancelled (#731).
        snapshot_id: quoteQuery.data?.snapshot_id,
      });
      window.location.assign(redirect_url);
    } catch (e) {
      const err = e as ApiError;
      const missing =
        err.code === "Onboarding.IncompleteApplication" && Array.isArray(err.details?.missing)
          ? (err.details.missing as string[]).filter((f) => f in MISSING_FIELD_HELP)
          : [];
      if (missing.length > 0) {
        const help = missing.map((f) => MISSING_FIELD_HELP[f]);
        const target = order.find((s) => help.some((h) => h.step === s));
        setError(`Before paying, we still need ${listPhrase(help.map((h) => h.label))}.`);
        if (target) setStep(target);
      } else if (err.code === "Billing.QuoteExpired") {
        // The quote on screen can no longer be charged. Re-price and stay put
        // so the parent reads the new amount before committing to it —
        // checkout must never substitute a figure they never saw (#731).
        void quoteQuery.refetch();
        setError(
          "The price we were holding ran out while you were filling things in. Please check the updated amount below and continue.",
        );
      } else {
        // S24: never show gateway detail ("Stripe connected account...") to a parent.
        setError(toCheckoutStartMessage(err, CHECKOUT_START_FAILED));
      }
      setSaving(false);
    }
  }

  const sessions = sessionsQuery.data?.sessions ?? [];
  const selectedSession =
    app.selected_session_id
      ? sessions.find((session) => session.session_id === app.selected_session_id)
      : undefined;
  return (
    <section data-testid="parent-onboarding">
      <OnboardingStyles />
      <Progress step={step} order={order} onStepClick={setStep} />

      {error && (
        <div
          role="alert"
          className="mb-4 rounded-xl border border-red-200 bg-red-50 p-3 text-sm text-red-800 animate-fade-in"
        >
          {error}
          <button type="button" onClick={() => setError(null)} className="ml-3 underline">
            Dismiss
          </button>
        </div>
      )}

      {/* Keyed wrapper replays the entrance animation each time the step changes */}
      <div key={step} className="animate-fade-in-up">
        {step === "parent" && (
          <ParentStep
            app={app}
            saving={saving}
            onSave={async (profile) => {
              if (await save({ parent_profile: profile })) {
                // Saved on the registration now (L9 C2); stop carrying it.
                clearReferralCode();
                // S21: the backend copied name and phone onto a blank profile.
                void queryClient.invalidateQueries({ queryKey: queryKeys.parent.profile() });
                advance();
              }
            }}
          />
        )}
        {step === "child" && (
          <ChildStep
            app={app}
            saving={saving}
            existingChildren={existingChildren}
            preselectedStudentId={preselectedChildId}
            onSave={async (profile) => {
              if (await save({ child_profile: profile })) advance();
            }}
          />
        )}
        {step === "waiver" && (
          <WaiverStep
            accepted={app.waiver_accepted}
            // Only a class-first academy asks for the waivers of the chosen
            // class; otherwise the request is exactly what it always was.
            sessionId={app.waiver_class_first ? app.selected_session_id : null}
            birthDate={app.child_profile?.date_of_birth ?? null}
            // S21: a family adding another child gets their signer name back.
            defaultSignerName={
              existingChildren.length > 0
                ? `${app.parent_profile.first_name} ${app.parent_profile.last_name}`.trim()
                : ""
            }
            childFirstName={app.child_profile.first_name}
            saving={saving}
            onAccept={async (signerName, initials) => {
              if (
                await save({ accept_waiver: true, signer_name: signerName, consent: true, initials })
              ) {
                advance();
              }
            }}
            onContinue={advance}
          />
        )}
        {step === "session" && (
          <SessionStep
            selected={app.selected_session_id}
            sessions={sessions}
            academyTimezone={academyTimezone}
            loading={sessionsQuery.isLoading}
            error={sessionsQuery.isError}
            onRetry={() => void sessionsQuery.refetch()}
            saving={saving}
            childLevel={app.child_profile.skill_level}
            onSelect={async (id) => {
              if (await save({ selected_session_id: id })) advance();
            }}
          />
        )}
        {step === "review" && (
          <ReviewStep
            app={app}
            selectedSession={selectedSession}
            academyTimezone={academyTimezone}
            quote={quoteQuery.data}
            quoteLoading={quoteQuery.isLoading}
            onCheckout={() => void goToCheckout()}
            onBack={() => setStep("parent")}
            saving={saving}
          />
        )}
      </div>
    </section>
  );
}

/**
 * #843: a pending step is `--rally-muted` (#64748b) on the `--rally-line`
 * (#e2e8f0) circle — 3.86:1, under WCAG AA. slate-600 clears it at 6.6:1.
 * Active and done steps keep their volt/amber treatment.
 */
const PENDING_STEP_COLOR = "#475569";

function Progress({
  step,
  order,
  onStepClick,
}: {
  step: Step;
  order: Step[];
  onStepClick: (s: Step) => void;
}) {
  const i = order.indexOf(step);
  return (
    <ol className="mb-6 flex items-center justify-between text-xs" data-testid="onboarding-progress">
      {order.map((s, idx) => {
        const done = idx < i;
        const active = idx === i;
        return (
          <li key={s} className="flex flex-1 items-center gap-1.5">
            <button
              type="button"
              onClick={() => onStepClick(s)}
              className="flex items-center gap-1.5 rounded transition-colors"
              style={{ color: active ? "#0a0f1c" : done ? "#854f0b" : PENDING_STEP_COLOR }}
            >
              <span
                className="flex h-5 w-5 items-center justify-center rounded-full text-[10px] font-semibold"
                style={{
                  background: active
                    ? "linear-gradient(135deg,#facc15,#f59e0b)"
                    : done
                      ? "#faeeda"
                      : "var(--rally-line)",
                  color: active ? "#0a0f1c" : done ? "#854f0b" : PENDING_STEP_COLOR,
                }}
              >
                {done ? "✓" : idx + 1}
              </span>
              <span className={`capitalize ${active ? "font-semibold" : "font-medium"}`}>{s === "session" ? "class" : s}</span>
            </button>
          </li>
        );
      })}
    </ol>
  );
}

function StepHeading({ children }: { children: React.ReactNode }) {
  return (
    <h2 className="font-display text-xl font-bold tracking-tight" style={{ color: "var(--rally-ink)" }}>
      {children}
    </h2>
  );
}

function ParentStep({
  app,
  onSave,
  saving,
}: {
  app: OnboardingApplication;
  onSave: (p: OnboardingApplication["parent_profile"]) => void;
  saving: boolean;
}) {
  const [v, setV] = useState(app.parent_profile);
  // Attach the ?ref= code captured on the academy page (L9 C2) after mount,
  // since localStorage is not readable during the server render.
  useEffect(() => {
    const code = storedReferralCode();
    if (code) setV((cur) => (cur.referral_code ? cur : { ...cur, referral_code: code }));
  }, []);
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        onSave(v);
      }}
      className="space-y-3"
    >
      <StepHeading>Your details (parent or guardian)</StepHeading>
      <p className="text-sm" style={{ color: "var(--rally-muted)" }}>
        Your own name and phone. Your child&apos;s details come next.
      </p>
      {v.referral_code ? (
        <p className="flex items-center justify-between gap-3 text-sm" data-testid="onboarding-referral-code">
          <span>
            Referral code <strong>{v.referral_code}</strong> will be added to your registration.
          </span>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={() => {
              clearReferralCode();
              setV({ ...v, referral_code: "" });
            }}
          >
            Remove
          </Button>
        </p>
      ) : null}
      <Field label="Your first name">
        <input value={v.first_name} onChange={(e) => setV({ ...v, first_name: e.target.value })} required />
      </Field>
      <Field label="Your last name">
        <input value={v.last_name} onChange={(e) => setV({ ...v, last_name: e.target.value })} required />
      </Field>
      {/*
        Required (issue #380): checkout rejects an application with no parent
        phone, so leaving this optional here would let a parent reach the
        payment step and be bounced with nothing to click. The form and the
        server-side completeness guard must agree.
      */}
      <Field label="Your phone">
        <input
          type="tel"
          value={v.phone}
          onChange={(e) => setV({ ...v, phone: e.target.value })}
          required
        />
      </Field>
      <Button type="submit" disabled={saving} variant="primary" full>
        Next
      </Button>
    </form>
  );
}

function ChildStep({
  app,
  onSave,
  saving,
  existingChildren,
  preselectedStudentId,
}: {
  app: OnboardingApplication;
  onSave: (p: OnboardingApplication["child_profile"]) => void;
  saving: boolean;
  /** #827: children this parent already has, from GET /parent/profile. */
  existingChildren: ParentSelfChild[];
  /** #827: the child the departed row pinned to the url, when there is one. */
  preselectedStudentId: string | null;
}) {
  const [v, setV] = useState(app.child_profile);
  const [noMedicalConditions, setNoMedicalConditions] = useState(
    app.child_profile.medical_notes === NO_MEDICAL_CONDITIONS_SENTINEL,
  );
  // #827: "somebody new" until the family says otherwise — a returning family
  // is pre-selected once their children load (below), never before.
  const [selection, setSelection] = useState<string>(NEW_CHILD_SELECTION);
  const preselectApplied = useRef(false);

  function chooseExistingChild(child: ParentSelfChild) {
    setSelection(child.student_id);
    setV((current) => childProfileFromExistingChild(child, current));
    setNoMedicalConditions(child.no_medical_conditions);
  }

  function chooseNewChild() {
    setSelection(NEW_CHILD_SELECTION);
  }

  // The children arrive from an async read, so the pin is applied when they
  // land — once. After that the family owns the choice: a re-run must never
  // yank their selection back to the pinned child.
  useEffect(() => {
    if (preselectApplied.current || existingChildren.length === 0) return;
    preselectApplied.current = true;
    const initial = initialChildSelection(existingChildren, preselectedStudentId);
    if (initial === NEW_CHILD_SELECTION) return;
    const child = existingChildren.find((c) => c.student_id === initial);
    if (child) chooseExistingChild(child);
  }, [existingChildren, preselectedStudentId]);

  const existingSelected = selection !== NEW_CHILD_SELECTION;
  const today = localIsoDate(new Date());
  const dobError = dateOfBirthError(v.date_of_birth, today);

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        if (dobError) return;
        onSave(v);
      }}
      className="space-y-3"
    >
      <StepHeading>Your child</StepHeading>
      {/* #827: a returning family picks the child they already have. Retyping
          the name is what used to produce a second student record — the
          backend binds an application to an existing student by name and date
          of birth, so a typo silently forked the child in two. */}
      {existingChildren.length > 0 && (
        <fieldset className="space-y-2" data-testid="onboarding-existing-child-picker">
          <legend className="text-sm font-medium" style={{ color: "var(--rally-ink)" }}>
            Who is this for?
          </legend>
          <div className="space-y-2 stagger-children" role="radiogroup" aria-label="Which child">
            {existingChildren.map((child) => {
              const selected = selection === child.student_id;
              return (
                <label
                  key={child.student_id}
                  data-testid={`onboarding-existing-child-${child.student_id}`}
                  className="relative flex min-h-11 items-center rounded-xl border px-3 text-sm transition-colors"
                  style={{
                    borderColor: selected ? "#facc15" : "var(--rally-line)",
                    background: selected ? "#fffbe9" : "white",
                    color: selected ? "#854f0b" : "var(--rally-ink)",
                    fontWeight: selected ? 600 : 400,
                  }}
                >
                  <input
                    type="radio"
                    name="onboarding-child"
                    value={child.student_id}
                    checked={selected}
                    onChange={() => chooseExistingChild(child)}
                    className="absolute inset-0 h-full w-full cursor-pointer opacity-0"
                  />
                  {child.full_name}
                </label>
              );
            })}
            <label
              data-testid="onboarding-child-new"
              className="relative flex min-h-11 items-center rounded-xl border px-3 text-sm transition-colors"
              style={{
                borderColor: existingSelected ? "var(--rally-line)" : "#facc15",
                background: existingSelected ? "white" : "#fffbe9",
                color: existingSelected ? "var(--rally-ink)" : "#854f0b",
                fontWeight: existingSelected ? 400 : 600,
              }}
            >
              <input
                type="radio"
                name="onboarding-child"
                value={NEW_CHILD_SELECTION}
                checked={!existingSelected}
                onChange={chooseNewChild}
                className="absolute inset-0 h-full w-full cursor-pointer opacity-0"
              />
              Add a new child
            </label>
          </div>
          {existingSelected && (
            <p className="text-xs" style={{ color: "var(--rally-muted)" }}>
              Their name and date of birth stay as we have them, so this joins their existing
              record instead of creating a second one.
            </p>
          )}
        </fieldset>
      )}
      <Field label="First name">
        <input
          value={v.first_name}
          onChange={(e) => setV({ ...v, first_name: e.target.value })}
          readOnly={existingSelected}
          required
        />
      </Field>
      <Field label="Last name">
        <input
          value={v.last_name}
          onChange={(e) => setV({ ...v, last_name: e.target.value })}
          readOnly={existingSelected}
          required
        />
      </Field>
      <Field label="Date of birth">
        <input
          type="date"
          autoComplete="bday"
          max={today}
          value={v.date_of_birth}
          onChange={(e) => setV({ ...v, date_of_birth: e.target.value })}
          readOnly={existingSelected}
          aria-invalid={dobError ? true : undefined}
          aria-describedby={dobError ? "onboarding-dob-error" : undefined}
          required
        />
      </Field>
      {dobError && (
        <p id="onboarding-dob-error" role="alert" className="text-sm text-red-700" data-testid="onboarding-dob-error">
          {dobError}
        </p>
      )}
      <fieldset className="space-y-2">
        <legend className="text-sm font-medium" style={{ color: "var(--rally-ink)" }}>Skill level</legend>
        <div className="grid grid-cols-3 gap-2 stagger-children" role="radiogroup" aria-label="Skill level">
          {(["beginner", "intermediate", "advanced"] as const).map((level) => {
            const selected = v.skill_level === level;
            return (
              <label
                key={level}
                className="relative flex min-h-11 flex-col items-center justify-center rounded-xl border px-2 py-1.5 text-center text-sm transition-colors"
                style={{
                  borderColor: selected ? "#facc15" : "var(--rally-line)",
                  background: selected ? "#fffbe9" : "white",
                  color: selected ? "#854f0b" : "var(--rally-ink)",
                  fontWeight: selected ? 600 : 400,
                }}
              >
                <input
                  type="radio"
                  name="skill-level"
                  value={level}
                  checked={selected}
                  onChange={() => setV({ ...v, skill_level: level })}
                  className="absolute inset-0 h-full w-full cursor-pointer opacity-0"
                />
                <span className="capitalize">{level}</span>
                <span className="mt-0.5 text-[11px] font-normal leading-tight" style={{ color: "var(--rally-muted)" }}>
                  {SKILL_LEVEL_HINTS[level]}
                </span>
              </label>
            );
          })}
        </div>
      </fieldset>
      <Field label="Emergency contact name">
        <input
          value={v.emergency_contact_name ?? ""}
          onChange={(e) => setV({ ...v, emergency_contact_name: e.target.value })}
          required
        />
      </Field>
      <Field label="Emergency contact phone">
        <input
          type="tel"
          value={v.emergency_contact_phone ?? ""}
          onChange={(e) => setV({ ...v, emergency_contact_phone: e.target.value })}
          required
        />
      </Field>
      <Field label="Medical notes">
        <textarea
          rows={2}
          placeholder="Allergies, conditions, or anything a coach should know"
          value={noMedicalConditions ? "" : (v.medical_notes ?? "")}
          onChange={(e) => {
            // Writing a note answers the question, so "none" no longer applies.
            setNoMedicalConditions(false);
            setV({ ...v, medical_notes: e.target.value });
          }}
          data-testid="onboarding-medical-notes"
        />
      </Field>
      <label className="flex items-center gap-2 text-sm" style={{ color: "var(--rally-ink)" }}>
        <input
          type="checkbox"
          checked={noMedicalConditions}
          onChange={(e) => {
            setNoMedicalConditions(e.target.checked);
            if (e.target.checked) setV({ ...v, medical_notes: NO_MEDICAL_CONDITIONS_SENTINEL });
            else if (v.medical_notes === NO_MEDICAL_CONDITIONS_SENTINEL)
              setV({ ...v, medical_notes: "" });
          }}
        />
        No known conditions or allergies
      </label>
      <Button type="submit" disabled={saving} variant="primary" full>
        Next
      </Button>
    </form>
  );
}

function WaiverStep({
  accepted,
  sessionId,
  birthDate,
  onAccept,
  onContinue,
  saving,
  defaultSignerName,
  childFirstName,
}: {
  accepted: boolean;
  sessionId: string | null;
  birthDate: string | null;
  defaultSignerName: string;
  childFirstName: string;
  onAccept: (signerName: string, initials: Record<string, Record<string, string>>) => void;
  onContinue: () => void;
  saving: boolean;
}) {
  // waiver_template_id -> {section key: initials}
  const [initials, setInitials] = useState<Record<string, Record<string, string>>>({});
  const waiverQuery = useQuery<RegistrationWaiver>({
    queryKey: sessionId
      ? ["parent", "registration-waiver", sessionId]
      : ["parent", "registration-waiver"],
    queryFn: () => getRegistrationWaiver(sessionId),
    staleTime: 300_000,
  });

  if (waiverQuery.isLoading) {
    return (
      <div className="space-y-4">
        <StepHeading>Waiver</StepHeading>
        <div className="h-32 rounded-2xl shimmer" />
      </div>
    );
  }

  if (waiverQuery.isError) {
    return (
      <div className="space-y-4">
        <StepHeading>Waiver</StepHeading>
        <div
          role="alert"
          className="rounded-xl border border-red-200 bg-red-50 p-3 text-sm text-red-800"
        >
          Could not load the waiver. Please try again.
        </div>
        <Button type="button" onClick={() => void waiverQuery.refetch()} variant="secondary">
          Retry
        </Button>
      </div>
    );
  }

  const waiver = waiverQuery.data;
  if (!waiver?.configured) {
    // S47 / D-11: no waiver to sign yet (none published, or only the starter
    // placeholder). The family continues; the academy collects it later.
    return (
      <div className="space-y-4">
        <StepHeading>Waiver</StepHeading>
        <p className="text-sm" style={{ color: "var(--rally-muted)" }} data-testid="onboarding-waiver-later">
          There is no waiver to sign right now. The academy will ask you to sign one later from
          your Waivers page.
        </p>
        <Button onClick={onContinue} disabled={saving} variant="primary" full>
          Continue →
        </Button>
      </div>
    );
  }

  const items = waiver.waivers ?? [];
  // Several waivers apply to this class: show each one, one button accepts all.
  const several = items.length > 1;
  // The child's date of birth picks the adult or parent/guardian sections.
  const path = signingPathFor(birthDate, new Date());
  const sectioned = items.map((item) => {
    const sections = parseWaiverSections(item.body);
    return { item, ageSplit: hasAgePaths(sections), needed: initialsNeeded(sections, [path]) };
  });
  const birthDateMissing = path === null && sectioned.some(({ ageSplit }) => ageSplit);
  const initialsDone = sectioned.every(({ item, needed }) =>
    initialsComplete(needed, initials[item.waiver_template_id]),
  );

  return (
    <div className="space-y-4">
      <StepHeading>{several ? "Waivers" : "Waiver"}</StepHeading>
      {defaultSignerName && !accepted ? (
        <p className="text-sm" style={{ color: "var(--rally-muted)" }} data-testid="onboarding-waiver-per-child">
          {waiverPerChildNote(childFirstName)}
        </p>
      ) : null}
      <div className="space-y-4" data-testid={several ? "onboarding-waivers" : undefined}>
        {sectioned.map(({ item, needed }) => (
          <div key={item.waiver_template_id} className="space-y-2">
            {several ? (
              <p className="text-sm font-semibold" style={{ color: "var(--rally-ink)" }}>
                {item.title ?? "Waiver"}
                <span className="ml-2 text-xs font-normal" style={{ color: "var(--rally-muted)" }}>
                  Version {item.version}
                </span>
              </p>
            ) : (
              <p className="text-xs" style={{ color: "var(--rally-muted)" }}>Version {item.version}</p>
            )}
            <div
              className="max-h-80 overflow-y-auto rounded-2xl border p-3"
              style={{ borderColor: "var(--rally-line)", background: "white" }}
            >
              <WaiverText
                body={item.body}
                needInitials={accepted ? [] : needed}
                initials={initials[item.waiver_template_id]}
                onInitials={(key, value) =>
                  setInitials((current) => ({
                    ...current,
                    [item.waiver_template_id]: { ...current[item.waiver_template_id], [key]: value },
                  }))
                }
              />
            </div>
          </div>
        ))}
      </div>
      {accepted ? (
        <Button onClick={onContinue} disabled={saving} variant="primary" full>
          Continue →
        </Button>
      ) : (
        <WaiverSignBlock
          childrenToSign={[]}
          consentText={waiver.consent_text ?? ""}
          busy={saving}
          error={null}
          blocked={
            birthDateMissing
              ? "Go back and add your child's date of birth: this waiver differs for participants under and over 18."
              : initialsDone
                ? null
                : "Initial each marked section above to sign."
          }
          label={() => (several ? "Sign waivers and continue" : "Sign and continue")}
          defaultSignerName={defaultSignerName}
          onSign={({ signerName }) => onAccept(signerName, initials)}
        />
      )}
    </div>
  );
}

function SessionStep({
  selected,
  sessions,
  academyTimezone,
  loading,
  error,
  onRetry,
  onSelect,
  saving,
  childLevel,
}: {
  selected: string | null;
  sessions: ParentAvailableSession[];
  /** The level chosen on the child step, for the level-mismatch note. */
  childLevel: string;
  academyTimezone: string | null;
  loading: boolean;
  error: boolean;
  onRetry: () => void;
  onSelect: (id: string) => void;
  saving: boolean;
}) {
  const levelNote = (session: ParentAvailableSession) => classLevelNote(session.title, childLevel);
  return (
    <div className="space-y-3">
      <StepHeading>Pick a class</StepHeading>

      {loading && (
        <div className="space-y-2" aria-label="Loading classes">
          {[0, 1, 2].map((i) => (
            <div key={i} className="h-24 rounded-2xl shimmer" />
          ))}
        </div>
      )}

      {error && (
        <div
          role="alert"
          className="rounded-xl border border-red-200 bg-red-50 p-3 text-sm text-red-800"
        >
          <p>Could not load classes.</p>
          <button type="button" onClick={onRetry} className="secondary mt-3">
            Retry
          </button>
        </div>
      )}

      {!loading && !error && sessions.length === 0 && (
        <p
          className="rounded-2xl border p-4 text-sm"
          style={{ borderColor: "var(--rally-line)", color: "var(--rally-muted)" }}
        >
          No classes are available right now.
        </p>
      )}

      {!loading && !error && sessions.length > 0 && (
        <ul className="space-y-2 stagger-children" aria-label="Available classes">
          {sessions.map((session) => {
            const isSelected = selected === session.session_id;
            const hasSeats = session.available_seats > 0;

            return (
              <li key={session.session_id}>
                <button
                  type="button"
                  disabled={saving || !hasSeats}
                  onClick={() => onSelect(session.session_id)}
                  className="w-full rounded-2xl border p-3 text-left transition active:scale-[0.99]"
                  style={{
                    borderColor: isSelected ? "#facc15" : "var(--rally-line)",
                    background: isSelected ? "#fffbe9" : "white",
                    opacity: hasSeats ? 1 : 0.55,
                  }}
                  aria-pressed={isSelected}
                >
                  <span className="flex items-start justify-between gap-3">
                    <span>
                      <span className="block font-semibold" style={{ color: "var(--rally-ink)" }}>
                        {session.title}
                      </span>
                      <span className="mt-1 block text-sm" style={{ color: "var(--rally-muted)" }}>
                        {session.location} · {formatSessionTime(session, academyTimezone)}
                      </span>
                    </span>
                    <span className="shrink-0 text-sm font-semibold" style={{ color: "var(--rally-ink)" }}>
                      {monthlyPriceLabel(session.amount_cents)}
                    </span>
                  </span>
                  <span className="mt-2 block text-xs" style={{ color: "var(--rally-muted)" }}>
                    {session.available_seats} of {session.capacity} seats open
                  </span>
                  {levelNote(session) && (
                    <span className="mt-2 block text-xs" style={{ color: "#854f0b" }} data-testid="onboarding-level-note">
                      {levelNote(session)}
                    </span>
                  )}
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

function ReviewStep({
  app,
  selectedSession,
  academyTimezone,
  quote,
  quoteLoading,
  onCheckout,
  onBack,
  saving,
}: {
  app: OnboardingApplication;
  selectedSession?: ParentAvailableSession;
  academyTimezone: string | null;
  quote?: EnrollmentQuote;
  quoteLoading: boolean;
  onCheckout: () => void;
  onBack: () => void;
  saving: boolean;
}) {
  return (
    <div className="space-y-4">
      <StepHeading>Review &amp; pay</StepHeading>
      <ul
        className="space-y-1 rounded-2xl border p-4 text-sm"
        style={{ borderColor: "var(--rally-line)", background: "white", color: "var(--rally-ink)" }}
      >
        <li>Parent or guardian: {app.parent_profile.first_name} {app.parent_profile.last_name}</li>
        <li>Child: {app.child_profile.first_name} {app.child_profile.last_name} ({skillLevelLabel(app.child_profile.skill_level)})</li>
        <li>
          Session:{" "}
          {selectedSession
            ? `${selectedSession.title} · ${formatSessionTime(selectedSession, academyTimezone)}`
            : app.selected_session_id ?? "—"}
        </li>
        {selectedSession && classLevelNote(selectedSession.title, app.child_profile.skill_level) && (
          <li style={{ color: "#854f0b" }} data-testid="onboarding-review-level-note">
            {classLevelNote(selectedSession.title, app.child_profile.skill_level)}
          </li>
        )}
        {quote ? (
          reviewPriceLines(quote).map((line) => <li key={line}>{line}</li>)
        ) : (
          <li>
            First month:{" "}
            {quoteLoading
              ? "Calculating..."
              : selectedSession
                ? monthlyPriceLabel(selectedSession.amount_cents)
                : "—"}
          </li>
        )}
        {quote?.quote_expires_at && (
          <li data-testid="onboarding-price-held">
            Price held until {formatShortDateTime(quote.quote_expires_at, academyTimezone)}
          </li>
        )}
        <li>Waiver: {app.waiver_accepted ? "Accepted" : "Not accepted"}</li>
      </ul>
      <div className="flex gap-2">
        <Button onClick={onBack} variant="secondary">
          Edit
        </Button>
        {/*
          Paying while the price still reads "Calculating…" is the one way back
          into #731: with no displayed snapshot to send, checkout falls back to
          quoting at click time, so the parent commits to a figure this screen
          never showed them.
        */}
        <Button
          onClick={onCheckout}
          disabled={saving || quoteLoading || !app.waiver_accepted || !app.selected_session_id}
          variant="primary"
          full
          data-testid="checkout-button"
        >
          {saving ? "Starting checkout…" : "Continue to checkout"}
        </Button>
      </div>
    </div>
  );
}

/**
 * "Thu, Sep 3 · 6:00 PM – 6:45 PM CDT".
 *
 * Renders in the session's own timezone, falling back to the academy's. The
 * previous implementation used `toLocaleTimeString(undefined, ...)` with no
 * `timeZone`, i.e. the browser's — which displayed a real 6:00 PM CDT class as
 * "1:00 PM" and told the parent the wrong hour at the point of payment. The
 * helper always appends a zone label, so a fallback is visible rather than
 * silent, and it parses offset-less timestamps as UTC (the backend emits some
 * rows naive) instead of as browser-local wall clock.
 */
function formatSessionTime(
  session: Pick<ParentAvailableSession, "start_at" | "end_at" | "timezone">,
  academyTimezone: string | null,
): string {
  return formatSessionOccurrence(session, academyTimezone);
}

function formatShortDateTime(value: string, academyTimezone: string | null): string {
  return formatAcademyMoment(value, academyTimezone);
}

function OnboardingStyles() {
  return (
    <style jsx global>{`
      [data-testid="parent-onboarding"] input:not([type="radio"]):not([type="checkbox"]),
      [data-testid="parent-onboarding"] select {
        width: 100%;
        min-height: 44px;
        padding: 0 0.875rem;
        border: 1px solid var(--rally-line);
        border-radius: 0.75rem;
        background: white;
        color: var(--rally-ink);
        outline: none;
        transition: border-color 0.15s, box-shadow 0.15s;
      }
      [data-testid="parent-onboarding"] input:not([type="radio"]):not([type="checkbox"]):focus,
      [data-testid="parent-onboarding"] select:focus {
        border-color: #facc15;
        box-shadow: 0 0 0 3px rgba(250, 204, 21, 0.18);
      }
      .primary {
        min-height: 44px;
        width: 100%;
        background: linear-gradient(135deg, #facc15, #f59e0b);
        color: #0a0f1c;
        font-weight: 600;
        border-radius: 0.75rem;
        padding: 0 1rem;
        transition: transform 0.1s;
      }
      .primary:active {
        transform: scale(0.97);
      }
      .primary:disabled {
        opacity: 0.5;
      }
      .secondary {
        min-height: 44px;
        padding: 0 1rem;
        border: 1px solid var(--rally-line);
        border-radius: 0.75rem;
        background: white;
        color: var(--rally-ink);
      }
    `}</style>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block text-sm">
      <span className="mb-1 block font-medium" style={{ color: "var(--rally-ink)" }}>{label}</span>
      <span className="block">
        {children}
      </span>
    </label>
  );
}
