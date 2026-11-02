"use client";

import { useId, useState } from "react";

import { Button } from "@/components/ds/button";

export interface WaiverSignChild {
  student_id: string;
  student_name: string;
}

export interface WaiverSignInput {
  signerName: string;
  studentIds: string[];
}

/**
 * The deliberate signing step: a typed full legal name, an unticked consent
 * box, and (with more than one child) a choice of whom to sign for. Sign stays
 * disabled until all three are complete, matching what the server enforces.
 */
export function WaiverSignBlock({
  childrenToSign,
  consentText,
  busy,
  error,
  label,
  onSign,
}: {
  childrenToSign: ReadonlyArray<WaiverSignChild>;
  consentText: string;
  busy: boolean;
  error: string | null;
  /** Button label for the chosen children, e.g. "Sign waiver for Alice". */
  label: (chosen: ReadonlyArray<WaiverSignChild>) => string;
  onSign: (input: WaiverSignInput) => void;
}) {
  const ids = useId();
  const [signerName, setSignerName] = useState("");
  const [consent, setConsent] = useState(false);
  const [unchosen, setUnchosen] = useState<ReadonlySet<string>>(new Set());

  // With one child left the checkboxes are hidden, so that child is always
  // chosen (a sibling deselected earlier may be all that remains after signing).
  const chosen =
    childrenToSign.length === 1
      ? childrenToSign
      : childrenToSign.filter((child) => !unchosen.has(child.student_id));
  const fullName = signerName.trim().split(/\s+/).filter(Boolean).length >= 2;
  const ready = fullName && consent && (childrenToSign.length === 0 || chosen.length > 0);

  function toggle(studentId: string) {
    setUnchosen((prev) => {
      const next = new Set(prev);
      if (next.has(studentId)) next.delete(studentId);
      else next.add(studentId);
      return next;
    });
  }

  return (
    <div className="space-y-4" data-testid="waiver-sign-block">
      {childrenToSign.length > 1 && (
        <fieldset className="space-y-2">
          <legend className="text-sm font-medium text-rally-ink">Sign for</legend>
          {childrenToSign.map((child) => (
            <label
              key={child.student_id}
              className="flex min-h-11 items-center gap-3 rounded-xl px-3 text-sm bg-rally-cobalt-50 text-rally-ink"
            >
              <input
                type="checkbox"
                className="h-5 w-5 accent-rally-cobalt-600"
                checked={!unchosen.has(child.student_id)}
                onChange={() => toggle(child.student_id)}
              />
              {child.student_name}
            </label>
          ))}
        </fieldset>
      )}

      <label className="block text-sm font-medium text-rally-ink" htmlFor={`${ids}-name`}>
        Full legal name
      </label>
      <input
        id={`${ids}-name`}
        value={signerName}
        onChange={(event) => setSignerName(event.target.value)}
        autoComplete="name"
        aria-describedby={`${ids}-name-hint`}
        className="-mt-2 h-11 w-full rounded-xl px-3 text-sm outline-none transition-colors border border-rally-line text-rally-ink focus:border-rally-cobalt-600 focus:ring-2 focus:ring-rally-cobalt-600/15"
        placeholder="First and last name"
      />
      <p id={`${ids}-name-hint`} className="-mt-2 text-xs text-rally-muted">
        Parent or legal guardian, as it appears on your ID.
      </p>

      <label className="flex items-start gap-3 text-sm text-rally-ink">
        <input
          type="checkbox"
          className="mt-0.5 h-5 w-5 shrink-0 accent-rally-cobalt-600"
          checked={consent}
          onChange={(event) => setConsent(event.target.checked)}
        />
        <span>{consentText}</span>
      </label>

      {error && (
        <p className="rounded-xl px-3 py-2 text-sm bg-status-red-50 text-status-red-800" role="alert">
          {error}
        </p>
      )}

      <Button
        type="button"
        full
        variant="primary"
        disabled={!ready || busy}
        className="disabled:opacity-60"
        onClick={() =>
          onSign({ signerName: signerName.trim(), studentIds: chosen.map((c) => c.student_id) })
        }
      >
        {busy ? "Signing..." : label(chosen)}
      </Button>
    </div>
  );
}
