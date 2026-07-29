"use client";

import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import {
  getRegistrationWaiver,
  listAvailableParentSessions,
  patchOnboarding,
  quoteEnrollment,
  startCheckout,
  startOnboarding,
  type EnrollmentQuote,
  type OnboardingApplication,
  type ParentAvailableSession,
  type RegistrationWaiver,
} from "@/lib/api/parent";

/**
 * Parent onboarding stepper.
 *
 * Steps: 1) parent info → 2) child info → 3) waiver → 4) select session → checkout.
 *
 * Autosaves on each step via PATCH; the application_id lives in URL state so
 * the parent can resume after a tab close.
 */

type Step = "parent" | "child" | "waiver" | "session" | "review";
const ORDER: Step[] = ["parent", "child", "waiver", "session", "review"];

export default function OnboardingStepperPage() {
  const [app, setApp] = useState<OnboardingApplication | null>(null);
  const [step, setStep] = useState<Step>("parent");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const sessionsQuery = useQuery({
    queryKey: ["parent", "sessions", "available"],
    queryFn: listAvailableParentSessions,
    staleTime: 60_000,
  });
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
        const fresh = await startOnboarding();
        setApp(fresh);
      } catch (e) {
        setError((e as Error).message);
      }
    })();
  }, []);

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

  function advance() {
    const i = ORDER.indexOf(step);
    if (i < ORDER.length - 1) setStep(ORDER[i + 1]);
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
      });
      window.location.assign(redirect_url);
    } catch (e) {
      setError((e as Error).message);
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
      <Progress step={step} onStepClick={setStep} />

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
              if (await save({ parent_profile: profile })) advance();
            }}
          />
        )}
        {step === "child" && (
          <ChildStep
            app={app}
            saving={saving}
            onSave={async (profile) => {
              if (await save({ child_profile: profile })) advance();
            }}
          />
        )}
        {step === "waiver" && (
          <WaiverStep
            accepted={app.waiver_accepted}
            saving={saving}
            onAccept={async () => {
              if (await save({ accept_waiver: true })) advance();
            }}
          />
        )}
        {step === "session" && (
          <SessionStep
            selected={app.selected_session_id}
            sessions={sessions}
            loading={sessionsQuery.isLoading}
            error={sessionsQuery.isError}
            onRetry={() => void sessionsQuery.refetch()}
            saving={saving}
            onSelect={async (id) => {
              if (await save({ selected_session_id: id })) advance();
            }}
          />
        )}
        {step === "review" && (
          <ReviewStep
            app={app}
            selectedSession={selectedSession}
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

function Progress({ step, onStepClick }: { step: Step; onStepClick: (s: Step) => void }) {
  const i = ORDER.indexOf(step);
  return (
    <ol className="mb-6 flex items-center justify-between text-xs" data-testid="onboarding-progress">
      {ORDER.map((s, idx) => {
        const done = idx < i;
        const active = idx === i;
        return (
          <li key={s} className="flex flex-1 items-center gap-1.5">
            <button
              type="button"
              onClick={() => onStepClick(s)}
              className="flex items-center gap-1.5 rounded transition-colors"
              style={{ color: active ? "#0a0f1c" : done ? "#854f0b" : "var(--rally-muted)" }}
            >
              <span
                className="flex h-5 w-5 items-center justify-center rounded-full text-[10px] font-semibold"
                style={{
                  background: active
                    ? "linear-gradient(135deg,#facc15,#f59e0b)"
                    : done
                      ? "#faeeda"
                      : "var(--rally-line)",
                  color: active ? "#0a0f1c" : done ? "#854f0b" : "var(--rally-muted)",
                }}
              >
                {done ? "✓" : idx + 1}
              </span>
              <span className={`capitalize ${active ? "font-semibold" : "font-medium"}`}>{s}</span>
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
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        onSave(v);
      }}
      className="space-y-3"
    >
      <StepHeading>Your details</StepHeading>
      <Field label="First name">
        <input value={v.first_name} onChange={(e) => setV({ ...v, first_name: e.target.value })} required />
      </Field>
      <Field label="Last name">
        <input value={v.last_name} onChange={(e) => setV({ ...v, last_name: e.target.value })} required />
      </Field>
      <Field label="Phone">
        <input value={v.phone} onChange={(e) => setV({ ...v, phone: e.target.value })} />
      </Field>
      <button type="submit" disabled={saving} className="primary">
        Next
      </button>
    </form>
  );
}

function ChildStep({
  app,
  onSave,
  saving,
}: {
  app: OnboardingApplication;
  onSave: (p: OnboardingApplication["child_profile"]) => void;
  saving: boolean;
}) {
  const [v, setV] = useState(app.child_profile);
  const [noMedicalConditions, setNoMedicalConditions] = useState(
    app.child_profile.medical_notes === "__none_declared__",
  );
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        onSave(v);
      }}
      className="space-y-3"
    >
      <StepHeading>Your child</StepHeading>
      <Field label="First name">
        <input value={v.first_name} onChange={(e) => setV({ ...v, first_name: e.target.value })} required />
      </Field>
      <Field label="Last name">
        <input value={v.last_name} onChange={(e) => setV({ ...v, last_name: e.target.value })} required />
      </Field>
      <Field label="Date of birth">
        <input
          type="text"
          inputMode="text"
          autoComplete="bday"
          placeholder="YYYY-MM-DD"
          pattern="\d{4}-\d{2}-\d{2}"
          maxLength={10}
          value={v.date_of_birth}
          onChange={(e) => setV({ ...v, date_of_birth: e.target.value })}
          required
        />
      </Field>
      <fieldset className="space-y-2">
        <legend className="text-sm font-medium" style={{ color: "var(--rally-ink)" }}>Skill level</legend>
        <div className="grid grid-cols-3 gap-2 stagger-children" role="radiogroup" aria-label="Skill level">
          {(["beginner", "intermediate", "advanced"] as const).map((level) => {
            const selected = v.skill_level === level;
            return (
              <label
                key={level}
                className="relative flex min-h-11 items-center justify-center rounded-xl border px-2 text-center text-sm capitalize transition-colors"
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
                {level}
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
          disabled={noMedicalConditions}
          value={noMedicalConditions ? "" : (v.medical_notes ?? "")}
          onChange={(e) => setV({ ...v, medical_notes: e.target.value })}
        />
      </Field>
      <label className="flex items-center gap-2 text-sm" style={{ color: "var(--rally-ink)" }}>
        <input
          type="checkbox"
          checked={noMedicalConditions}
          onChange={(e) => {
            setNoMedicalConditions(e.target.checked);
            if (e.target.checked) setV({ ...v, medical_notes: "__none_declared__" });
            else if (v.medical_notes === "__none_declared__") setV({ ...v, medical_notes: "" });
          }}
        />
        No known conditions or allergies
      </label>
      <button type="submit" disabled={saving} className="primary">
        Next
      </button>
    </form>
  );
}

function WaiverStep({
  accepted,
  onAccept,
  saving,
}: {
  accepted: boolean;
  onAccept: () => void;
  saving: boolean;
}) {
  const waiverQuery = useQuery<RegistrationWaiver>({
    queryKey: ["parent", "registration-waiver"],
    queryFn: getRegistrationWaiver,
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
        <button type="button" onClick={() => void waiverQuery.refetch()} className="secondary">
          Retry
        </button>
      </div>
    );
  }

  const waiver = waiverQuery.data;
  if (!waiver?.configured) {
    return (
      <div className="space-y-4">
        <StepHeading>Waiver</StepHeading>
        <p className="text-sm" style={{ color: "var(--rally-muted)" }}>
          Waiver not configured yet — an academy admin must publish a waiver template and
          assign it to registration.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <StepHeading>Waiver</StepHeading>
      {waiver.version && (
        <p className="text-xs" style={{ color: "var(--rally-muted)" }}>Version {waiver.version}</p>
      )}
      <div
        className="max-h-60 overflow-y-auto rounded-2xl border p-3 text-sm"
        style={{ borderColor: "var(--rally-line)", background: "white", color: "var(--rally-ink)" }}
      >
        <p className="whitespace-pre-wrap">{waiver.body}</p>
      </div>
      <button onClick={onAccept} disabled={saving} className="primary">
        {accepted ? "Continue →" : "I Accept"}
      </button>
    </div>
  );
}

function SessionStep({
  selected,
  sessions,
  loading,
  error,
  onRetry,
  onSelect,
  saving,
}: {
  selected: string | null;
  sessions: ParentAvailableSession[];
  loading: boolean;
  error: boolean;
  onRetry: () => void;
  onSelect: (id: string) => void;
  saving: boolean;
}) {
  return (
    <div className="space-y-3">
      <StepHeading>Pick a session</StepHeading>

      {loading && (
        <div className="space-y-2" aria-label="Loading sessions">
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
          <p>Could not load sessions.</p>
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
          No sessions are available right now.
        </p>
      )}

      {!loading && !error && sessions.length > 0 && (
        <ul className="space-y-2 stagger-children" aria-label="Available sessions">
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
                        {session.location} · {formatSessionTime(session)}
                      </span>
                    </span>
                    <span className="shrink-0 text-sm font-semibold" style={{ color: "var(--rally-ink)" }}>
                      {formatCents(session.amount_cents)}
                    </span>
                  </span>
                  <span className="mt-2 block text-xs" style={{ color: "var(--rally-muted)" }}>
                    {session.available_seats} of {session.capacity} seats open
                  </span>
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
  quote,
  quoteLoading,
  onCheckout,
  onBack,
  saving,
}: {
  app: OnboardingApplication;
  selectedSession?: ParentAvailableSession;
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
        <li>Parent: {app.parent_profile.first_name} {app.parent_profile.last_name}</li>
        <li>Child: {app.child_profile.first_name} {app.child_profile.last_name} ({app.child_profile.skill_level || "—"})</li>
        <li>
          Session:{" "}
          {selectedSession
            ? `${selectedSession.title} · ${formatSessionTime(selectedSession)}`
            : app.selected_session_id ?? "—"}
        </li>
        <li>
          First month:{" "}
          {quote
            ? `${formatCents(quote.amount_due_cents)} · billed for ${quote.billable_remaining_classes_this_month} of ${quote.total_eligible_classes_this_month} classes this month`
            : quoteLoading
              ? "Calculating..."
              : selectedSession
                ? formatCents(selectedSession.amount_cents)
                : "—"}
        </li>
        {quote && <li>Starting next month: {formatCents(quote.next_billing_amount_cents)}</li>}
        {quote?.quote_expires_at && <li>Quote expires: {formatShortDateTime(quote.quote_expires_at)}</li>}
        <li>Waiver: {app.waiver_accepted ? "Accepted" : "Not accepted"}</li>
      </ul>
      <div className="flex gap-2">
        <button onClick={onBack} className="secondary">
          Edit
        </button>
        <button
          onClick={onCheckout}
          disabled={saving || !app.waiver_accepted || !app.selected_session_id}
          className="primary"
          data-testid="checkout-button"
        >
          {saving ? "Starting checkout…" : "Continue to checkout"}
        </button>
      </div>
    </div>
  );
}

function formatSessionTime(session: Pick<ParentAvailableSession, "start_at" | "end_at">): string {
  const start = new Date(session.start_at);
  const end = new Date(session.end_at);
  const date = start.toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
  });
  const startTime = start.toLocaleTimeString(undefined, {
    hour: "numeric",
    minute: "2-digit",
  });
  const endTime = end.toLocaleTimeString(undefined, {
    hour: "numeric",
    minute: "2-digit",
  });

  return `${date}, ${startTime} - ${endTime}`;
}

function formatShortDateTime(value: string): string {
  return new Date(value).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

function formatCents(cents: number): string {
  return new Intl.NumberFormat(undefined, {
    style: "currency",
    currency: "USD",
  }).format(cents / 100);
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
