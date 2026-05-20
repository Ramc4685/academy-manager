"use client";

import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import {
  listAvailableParentSessions,
  patchOnboarding,
  quoteEnrollment,
  startCheckout,
  startOnboarding,
  type EnrollmentQuote,
  type OnboardingApplication,
  type ParentAvailableSession,
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

  if (error) return <p className="text-red-600">{error}</p>;
  if (!app) return <p className="text-neutral-500">Loading…</p>;

  async function save(patch: Parameters<typeof patchOnboarding>[1]) {
    if (!app) return;
    setSaving(true);
    setError(null);
    try {
      const next = await patchOnboarding(app.application_id, patch);
      setApp(next);
    } catch (e) {
      setError((e as Error).message);
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
      <Progress step={step} />

      {step === "parent" && (
        <ParentStep
          app={app}
          saving={saving}
          onSave={async (profile) => {
            await save({ parent_profile: profile });
            advance();
          }}
        />
      )}
      {step === "child" && (
        <ChildStep
          app={app}
          saving={saving}
          onSave={async (profile) => {
            await save({ child_profile: profile });
            advance();
          }}
        />
      )}
      {step === "waiver" && (
        <WaiverStep
          accepted={app.waiver_accepted}
          saving={saving}
          onAccept={async () => {
            await save({ accept_waiver: true });
            advance();
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
            await save({ selected_session_id: id });
            advance();
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
    </section>
  );
}

function Progress({ step }: { step: Step }) {
  const i = ORDER.indexOf(step);
  return (
    <ol className="mb-6 flex items-center justify-between text-xs" data-testid="onboarding-progress">
      {ORDER.map((s, idx) => (
        <li key={s} className={idx <= i ? "font-semibold text-blue-600" : "text-neutral-400"}>
          {idx + 1}. {s}
        </li>
      ))}
    </ol>
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
      <h2 className="text-xl font-semibold">Your details</h2>
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
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        onSave(v);
      }}
      className="space-y-3"
    >
      <h2 className="text-xl font-semibold">Your child</h2>
      <Field label="First name">
        <input value={v.first_name} onChange={(e) => setV({ ...v, first_name: e.target.value })} required />
      </Field>
      <Field label="Last name">
        <input value={v.last_name} onChange={(e) => setV({ ...v, last_name: e.target.value })} required />
      </Field>
      <Field label="Date of birth">
        <input type="date" value={v.date_of_birth} onChange={(e) => setV({ ...v, date_of_birth: e.target.value })} required />
      </Field>
      <Field label="Skill level">
        <select value={v.skill_level} onChange={(e) => setV({ ...v, skill_level: e.target.value as never })}>
          <option value="">—</option>
          <option value="beginner">Beginner</option>
          <option value="intermediate">Intermediate</option>
          <option value="advanced">Advanced</option>
        </select>
      </Field>
      <button type="submit" disabled={saving} className="primary">
        Next
      </button>
    </form>
  );
}

function WaiverStep({ accepted, onAccept, saving }: { accepted: boolean; onAccept: () => void; saving: boolean }) {
  return (
    <div className="space-y-4">
      <h2 className="text-xl font-semibold">Waiver</h2>
      <p className="text-sm text-neutral-700 dark:text-neutral-300">
        I acknowledge the program&apos;s standard liability waiver and agree to its terms.
      </p>
      <button onClick={onAccept} disabled={saving || accepted} className="primary">
        {accepted ? "Accepted ✓" : "Accept"}
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
      <h2 className="text-xl font-semibold">Pick a session</h2>

      {loading && (
        <div className="space-y-2" aria-label="Loading sessions">
          {[0, 1, 2].map((i) => (
            <div key={i} className="h-24 animate-pulse rounded-lg bg-neutral-100 dark:bg-neutral-800" />
          ))}
        </div>
      )}

      {error && (
        <div
          role="alert"
          className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-800 dark:border-red-900 dark:bg-red-950 dark:text-red-200"
        >
          <p>Could not load sessions.</p>
          <button type="button" onClick={onRetry} className="secondary mt-3">
            Retry
          </button>
        </div>
      )}

      {!loading && !error && sessions.length === 0 && (
        <p className="rounded-lg border border-neutral-200 p-4 text-sm text-neutral-500 dark:border-neutral-800">
          No sessions are available right now.
        </p>
      )}

      {!loading && !error && sessions.length > 0 && (
        <ul className="space-y-2" aria-label="Available sessions">
          {sessions.map((session) => {
            const isSelected = selected === session.session_id;
            const hasSeats = session.available_seats > 0;

            return (
              <li key={session.session_id}>
                <button
                  type="button"
                  disabled={saving || !hasSeats}
                  onClick={() => onSelect(session.session_id)}
                  className={`w-full rounded-lg border p-3 text-left transition ${
                    isSelected
                      ? "border-blue-600 bg-blue-50 dark:border-blue-400 dark:bg-blue-950/40"
                      : "border-neutral-200 bg-white hover:border-blue-300 dark:border-neutral-800 dark:bg-neutral-950"
                  } ${!hasSeats ? "opacity-55" : ""}`}
                  aria-pressed={isSelected}
                >
                  <span className="flex items-start justify-between gap-3">
                    <span>
                      <span className="block font-semibold text-neutral-950 dark:text-white">
                        {session.title}
                      </span>
                      <span className="mt-1 block text-sm text-neutral-600 dark:text-neutral-400">
                        {session.location} · {formatSessionTime(session)}
                      </span>
                    </span>
                    <span className="shrink-0 text-sm font-semibold text-neutral-950 dark:text-white">
                      {formatCents(session.amount_cents)}
                    </span>
                  </span>
                  <span className="mt-2 block text-xs text-neutral-500">
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
      <h2 className="text-xl font-semibold">Review &amp; pay</h2>
      <ul className="text-sm space-y-1">
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
      [data-testid="parent-onboarding"] input,
      [data-testid="parent-onboarding"] select {
        width: 100%;
        min-height: 44px;
        padding: 0 0.75rem;
        border: 1px solid var(--field-border, #d4d4d8);
        border-radius: 0.375rem;
        background: transparent;
      }
      .primary {
        min-height: 44px;
        width: 100%;
        background: #2563eb;
        color: white;
        border-radius: 0.375rem;
        padding: 0 1rem;
      }
      .primary:disabled {
        opacity: 0.5;
      }
      .secondary {
        min-height: 44px;
        padding: 0 1rem;
        border: 1px solid #d4d4d8;
        border-radius: 0.375rem;
      }
    `}</style>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block text-sm">
      <span className="mb-1 block font-medium">{label}</span>
      <span className="block">
        {children}
      </span>
    </label>
  );
}
