"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import {
  getOnboardingStatus,
  patchOnboarding,
  startCheckout,
  startOnboarding,
  type OnboardingApplication,
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
  const router = useRouter();
  const [app, setApp] = useState<OnboardingApplication | null>(null);
  const [step, setStep] = useState<Step>("parent");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

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
    const { redirect_url } = await startCheckout({
      application_id: app.application_id,
      amount_cents: 15000, // session price from admin config in a full impl
      success_url: `${origin}/parent/checkout/return?application_id=${app.application_id}`,
      cancel_url: `${origin}/parent/onboarding`,
    });
    window.location.assign(redirect_url);
  }

  return (
    <section data-testid="parent-onboarding">
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
          onCheckout={() => void goToCheckout()}
          onBack={() => setStep("parent")}
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
  onSelect,
  saving,
}: {
  selected: string | null;
  onSelect: (id: string) => void;
  saving: boolean;
}) {
  // In the full app, this loads available sessions from a /parent/sessions
  // endpoint. For now we let the parent paste a session id (admin gives it to
  // them out-of-band during onboarding).
  const [id, setId] = useState(selected ?? "");
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        if (id) onSelect(id);
      }}
      className="space-y-3"
    >
      <h2 className="text-xl font-semibold">Pick a session</h2>
      <Field label="Session ID">
        <input value={id} onChange={(e) => setId(e.target.value)} required />
      </Field>
      <button type="submit" disabled={saving || !id} className="primary">
        Next
      </button>
    </form>
  );
}

function ReviewStep({
  app,
  onCheckout,
  onBack,
}: {
  app: OnboardingApplication;
  onCheckout: () => void;
  onBack: () => void;
}) {
  return (
    <div className="space-y-4">
      <h2 className="text-xl font-semibold">Review &amp; pay</h2>
      <ul className="text-sm space-y-1">
        <li>Parent: {app.parent_profile.first_name} {app.parent_profile.last_name}</li>
        <li>Child: {app.child_profile.first_name} {app.child_profile.last_name} ({app.child_profile.skill_level || "—"})</li>
        <li>Session: {app.selected_session_id ?? "—"}</li>
        <li>Waiver: {app.waiver_accepted ? "Accepted" : "Not accepted"}</li>
      </ul>
      <div className="flex gap-2">
        <button onClick={onBack} className="secondary">
          Edit
        </button>
        <button
          onClick={onCheckout}
          disabled={!app.waiver_accepted || !app.selected_session_id}
          className="primary"
          data-testid="checkout-button"
        >
          Continue to checkout
        </button>
      </div>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block text-sm">
      <span className="mb-1 block font-medium">{label}</span>
      <span className="block">
        {children}
      </span>
      <style jsx>{`
        input, select {
          width: 100%;
          min-height: 44px;
          padding: 0 0.75rem;
          border: 1px solid var(--field-border, #d4d4d8);
          border-radius: 0.375rem;
          background: transparent;
        }
        :global(.primary) {
          min-height: 44px;
          width: 100%;
          background: #2563eb;
          color: white;
          border-radius: 0.375rem;
          padding: 0 1rem;
        }
        :global(.primary:disabled) { opacity: 0.5; }
        :global(.secondary) {
          min-height: 44px;
          padding: 0 1rem;
          border: 1px solid #d4d4d8;
          border-radius: 0.375rem;
        }
      `}</style>
    </label>
  );
}
