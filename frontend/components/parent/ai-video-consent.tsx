"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { Button } from "@/components/ds/button";
import { Card } from "@/components/ds/card";
import { Chip } from "@/components/ds/chip";
import {
  getParentAiVideoConsent,
  grantParentAiVideoConsent,
  revokeParentAiVideoConsent,
  type ParentAiVideoConsentView,
} from "@/lib/api/parent";
import { queryKeys } from "@/lib/query/keys";

/**
 * Optional, per-child AI/video consent (Phase 3 E1). Separate from the
 * required waivers: nothing is blocked by leaving it off, and it can be
 * revoked here at any time.
 */
export function AiVideoConsentCard() {
  const queryClient = useQueryClient();
  const query = useQuery({
    queryKey: queryKeys.parent.aiVideoConsent(),
    queryFn: getParentAiVideoConsent,
    retry: false,
  });
  const mutation = useMutation({
    mutationFn: (input: { studentId: string; grant: boolean; textVersion: string }) =>
      input.grant
        ? grantParentAiVideoConsent(input.studentId, input.textVersion)
        : revokeParentAiVideoConsent(input.studentId),
    onSuccess: (view) => queryClient.setQueryData(queryKeys.parent.aiVideoConsent(), view),
  });
  if (!query.data || query.data.children.length === 0) return null;
  const view = query.data;
  return (
    <AiVideoConsentBlock
      view={view}
      busyStudentId={mutation.isPending ? (mutation.variables?.studentId ?? null) : null}
      error={mutation.isError ? "Could not save your choice. Please try again." : null}
      onGrant={(studentId) =>
        mutation.mutate({ studentId, grant: true, textVersion: view.text_version })
      }
      onRevoke={(studentId) =>
        mutation.mutate({ studentId, grant: false, textVersion: view.text_version })
      }
    />
  );
}

export function AiVideoConsentBlock({
  view,
  busyStudentId,
  error,
  onGrant,
  onRevoke,
}: {
  view: ParentAiVideoConsentView;
  busyStudentId: string | null;
  error: string | null;
  onGrant: (studentId: string) => void;
  onRevoke: (studentId: string) => void;
}) {
  const [ticked, setTicked] = useState<Record<string, boolean>>({});
  return (
    <Card data-testid="parent-ai-video-consent">
      <h2 className="font-display text-lg font-semibold tracking-tight text-rally-ink">
        AI video consent (optional)
      </h2>
      <p className="mt-1 text-sm text-rally-muted">
        Separate from the waivers above. Leaving it off changes nothing about classes.
      </p>
      {view.placeholder && (
        <p
          className="mt-3 rounded-xl px-3 py-2 text-sm bg-status-amber-50 text-status-amber-800"
          role="note"
        >
          This text is a draft awaiting legal review. No video is analysed while it is a draft.
        </p>
      )}
      <p className="mt-3 rounded-xl border border-rally-line bg-rally-paper p-3 text-sm text-rally-ink whitespace-pre-line">
        {view.text}
      </p>
      <p className="mt-1 text-xs text-rally-muted">Version {view.text_version}</p>
      {error && (
        <p className="mt-3 text-sm text-status-red-800" role="alert">
          {error}
        </p>
      )}
      <ul className="mt-3 space-y-2">
        {view.children.map((child) => {
          const busy = busyStudentId === child.student_id;
          const granted = child.status === "granted";
          const checkboxId = `ai-video-consent-${child.student_id}`;
          return (
            <li
              key={child.student_id}
              className="flex flex-wrap items-center justify-between gap-3 rounded-xl px-3 py-2.5 text-sm bg-rally-cobalt-50"
            >
              <span className="font-medium text-rally-ink">{child.student_name}</span>
              {granted ? (
                <span className="flex items-center gap-2">
                  <Chip variant="approved" label="Opted in" />
                  <Button
                    size="sm"
                    variant="danger"
                    disabled={busy}
                    onClick={() => onRevoke(child.student_id)}
                  >
                    Revoke
                  </Button>
                </span>
              ) : (
                <span className="flex items-center gap-2">
                  {child.status === "revoked" && <Chip variant="expired" label="Revoked" />}
                  <label htmlFor={checkboxId} className="flex items-center gap-1.5 text-rally-ink">
                    <input
                      id={checkboxId}
                      type="checkbox"
                      checked={Boolean(ticked[child.student_id])}
                      onChange={(event) =>
                        setTicked((current) => ({
                          ...current,
                          [child.student_id]: event.target.checked,
                        }))
                      }
                    />
                    I agree
                  </label>
                  <Button
                    size="sm"
                    variant="secondary"
                    disabled={busy || !ticked[child.student_id]}
                    onClick={() => onGrant(child.student_id)}
                  >
                    Opt in
                  </Button>
                </span>
              )}
            </li>
          );
        })}
      </ul>
    </Card>
  );
}
