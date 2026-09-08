"use client";

import { listCoachMessages, markCoachMessageRead } from "@/lib/api/v2/messages";
import { queryKeys } from "@/lib/query/keys";
import { PersonaInbox } from "@/components/messages/PersonaInbox";
import {
  AssistantCoachDeniedNotice,
  useIsAssistantCoach,
} from "@/components/coach/coach-surface-context";

export default function CoachMessagesPage() {
  // Assistants are not a messaging audience (the BFF 404s the inbox), so the
  // page says so instead of rendering an inbox that can never load.
  const assistant = useIsAssistantCoach();
  if (assistant) {
    return <AssistantCoachDeniedNotice surface="Messaging" />;
  }
  return (
    <PersonaInbox
      queryKey={queryKeys.coach.messages()}
      listMessages={listCoachMessages}
      markMessageRead={markCoachMessageRead}
      testId="coach"
      emptyStateDescription="Broadcasts and DMs from admin will show up here."
    />
  );
}
