"use client";

import { createContext, useContext } from "react";

/**
 * Assistant-coach scope for the coach shell, resolved once by the layout's
 * `usePersonaAuth("coach", …)` and shared with pages so they do not each
 * re-run the /me check. Defaults to `false`: a page rendered outside the
 * provider keeps the full coach surface, which is the real-coach case.
 */
const AssistantCoachContext = createContext<boolean>(false);

export function CoachSurfaceProvider({
  assistant,
  children,
}: {
  assistant: boolean;
  children: React.ReactNode;
}) {
  return (
    <AssistantCoachContext.Provider value={assistant}>{children}</AssistantCoachContext.Provider>
  );
}

/**
 * True when the signed-in user is an assistant coach only (holds
 * `assistant_coach` and none of coach/admin/owner). Lead-only surfaces —
 * messaging, announcements, billing previews, pay — hide behind this.
 */
export function useIsAssistantCoach(): boolean {
  return useContext(AssistantCoachContext);
}

/** Shown in place of a lead-only coach page to an assistant coach. */
export function AssistantCoachDeniedNotice({ surface }: { surface: string }) {
  return (
    <div
      role="status"
      data-testid="coach-assistant-denied"
      className="rounded-md border px-4 py-3 text-sm"
      style={{
        background: "rgba(250,204,21,0.12)",
        borderColor: "rgba(250,204,21,0.5)",
        color: "var(--rally-ink)",
      }}
    >
      <span className="font-semibold">Assistant coach.</span> {surface} is for the lead coach.
      You can mark attendance, update skills and add notes on the sessions you&apos;re assigned
      to.
    </div>
  );
}
