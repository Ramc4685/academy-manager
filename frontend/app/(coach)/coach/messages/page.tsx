"use client";

import { listCoachMessages, markCoachMessageRead } from "@/lib/api/v2/messages";
import { queryKeys } from "@/lib/query/keys";
import { PersonaInbox } from "@/components/messages/PersonaInbox";

export default function CoachMessagesPage() {
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
