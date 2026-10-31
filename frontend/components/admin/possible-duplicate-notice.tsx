"use client";

/**
 * People CRM Phase 4c: "Possible match: <name> - open" on the Add parent /
 * Add user / Add contact forms.
 *
 * `usePossibleDuplicateCheck` asks the backend when an email or phone field
 * is left (debounced, so tabbing through both fields sends one request) and
 * keeps only the answer to the latest question. `PossibleDuplicateNotice`
 * renders it inside an always-mounted `aria-live="polite"` region, so a
 * screen reader hears the warning without losing its place.
 *
 * A warning, never a gate: nothing here disables a submit button, and a
 * failed check shows nothing (the form must keep working when the check
 * cannot). The link opens in a new tab so the half-filled form survives.
 */
import { useCallback, useEffect, useRef, useState } from "react";

import {
  checkPossibleDuplicates,
  duplicateKindLabel,
  duplicateProbe,
  sameProbe,
  type DuplicateMatch,
  type DuplicateProbe,
} from "@/lib/api/admin-people-duplicates";

export const DUPLICATE_CHECK_DEBOUNCE_MS = 300;

export interface DuplicateCheckFields {
  email?: string | null;
  phone?: string | null;
  name?: string | null;
}

export function usePossibleDuplicateCheck() {
  const [matches, setMatches] = useState<DuplicateMatch[]>([]);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const asked = useRef<DuplicateProbe | null>(null);
  const sequence = useRef(0);

  useEffect(
    () => () => {
      if (timer.current) clearTimeout(timer.current);
      sequence.current += 1; // drop any answer that lands after unmount
    },
    [],
  );

  const check = useCallback((fields: DuplicateCheckFields) => {
    if (timer.current) clearTimeout(timer.current);
    const probe = duplicateProbe(fields);
    if (probe === null) {
      asked.current = null;
      sequence.current += 1;
      setMatches([]);
      return;
    }
    if (sameProbe(probe, asked.current)) return;
    timer.current = setTimeout(() => {
      asked.current = probe;
      const mine = ++sequence.current;
      checkPossibleDuplicates(probe)
        .then((response) => {
          if (mine === sequence.current) setMatches(response.matches ?? []);
        })
        .catch(() => {
          // Best effort: no notice when the check fails; the form carries on.
          if (mine === sequence.current) setMatches([]);
        });
    }, DUPLICATE_CHECK_DEBOUNCE_MS);
  }, []);

  const reset = useCallback(() => {
    if (timer.current) clearTimeout(timer.current);
    asked.current = null;
    sequence.current += 1;
    setMatches([]);
  }, []);

  return { matches, check, reset };
}

function matchDetail(match: DuplicateMatch): string {
  const contact = [match.email_masked, match.phone_masked].filter(Boolean).join(", ");
  const kind = duplicateKindLabel(match.kind);
  return contact ? `${kind}, ${contact}` : kind;
}

export function PossibleDuplicateNotice({
  matches,
  testId = "possible-duplicate-notice",
}: {
  matches: DuplicateMatch[];
  testId?: string;
}) {
  const [first, ...rest] = matches;
  return (
    <div aria-live="polite" role="status" data-testid={`${testId}-region`}>
      {first && (
        <div
          className="rounded-md border border-status-amber-500 bg-status-amber-50 p-3 text-sm text-status-amber-800"
          data-testid={testId}
        >
          <p>
            <span className="font-semibold">Possible match:</span> {first.display_name}{" "}
            <span className="text-xs">({matchDetail(first)})</span>
            {first.link && (
              <>
                {" - "}
                <a
                  href={first.link}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="font-semibold underline underline-offset-2"
                  data-testid={`${testId}-open`}
                >
                  open
                </a>
              </>
            )}
          </p>
          {rest.length > 0 && (
            <ul className="mt-1 space-y-0.5 text-xs">
              {rest.map((match, index) => (
                <li key={`${match.kind}-${match.link ?? match.display_name}-${index}`}>
                  {match.display_name} ({matchDetail(match)})
                  {match.link && (
                    <>
                      {" - "}
                      <a
                        href={match.link}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="underline underline-offset-2"
                      >
                        open
                      </a>
                    </>
                  )}
                </li>
              ))}
            </ul>
          )}
          <p className="mt-1 text-xs">You can still save if this is someone new.</p>
        </div>
      )}
    </div>
  );
}
