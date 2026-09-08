"use client";

import { createContext, useContext, useMemo } from "react";

export interface CoachSurfaceScope {
  /**
   * Assistant coach *only* (holds `assistant_coach` and none of
   * coach/admin/owner). Lead-only surfaces — messaging, announcements, billing
   * previews, pay — hide behind this.
   */
  assistant: boolean;
  /** `/me` user_id of the signed-in coach; null outside the provider. */
  userId: string | null;
  /**
   * Owner/admin covering the coach surface (#632). Only they may change the
   * visibility of a note they did not write; `SetSkillNoteVisibility` 404s
   * every other non-author.
   */
  supervisor: boolean;
}

/**
 * Coach-shell scope, resolved once by the layout's `usePersonaAuth("coach", …)`
 * and shared with pages so they do not each re-run the /me check. The default
 * keeps the full coach surface (the real-coach case) but knows no identity, so
 * author-gated controls stay hidden outside the provider.
 */
const CoachSurfaceContext = createContext<CoachSurfaceScope>({
  assistant: false,
  userId: null,
  supervisor: false,
});

export function CoachSurfaceProvider({
  assistant,
  userId,
  supervisor,
  children,
}: {
  assistant: boolean;
  userId: string | null;
  supervisor: boolean;
  children: React.ReactNode;
}) {
  const value = useMemo(
    () => ({ assistant, userId, supervisor }),
    [assistant, userId, supervisor],
  );
  return <CoachSurfaceContext.Provider value={value}>{children}</CoachSurfaceContext.Provider>;
}

/** The whole scope, for pages that need identity as well as the assistant flag. */
export function useCoachSurface(): CoachSurfaceScope {
  return useContext(CoachSurfaceContext);
}

/**
 * True when the signed-in user is an assistant coach only (holds
 * `assistant_coach` and none of coach/admin/owner). Lead-only surfaces —
 * messaging, announcements, billing previews, pay — hide behind this.
 */
export function useIsAssistantCoach(): boolean {
  return useContext(CoachSurfaceContext).assistant;
}

/**
 * May this viewer change who sees `authorId`'s note?
 *
 * `ListSkillNotes` returns every author's notes for a student + skill, but
 * `SetSkillNoteVisibility` 404s a caller who is neither the author nor a
 * supervisor — so a Share toggle on a colleague's note could never succeed.
 * Assistants may never change visibility at all (403).
 */
export function canChangeNoteVisibility(
  scope: CoachSurfaceScope,
  authorId: string | null | undefined,
): boolean {
  if (scope.assistant) return false;
  if (scope.supervisor) return true;
  return Boolean(scope.userId) && scope.userId === authorId;
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
