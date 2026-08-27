"use client";

import { listParentMessages, markParentMessageRead } from "@/lib/api/v2/messages";
import { queryKeys } from "@/lib/query/keys";
import { PersonaInbox } from "@/components/messages/PersonaInbox";

export default function ParentMessagesPage() {
  return (
    <PersonaInbox
      queryKey={queryKeys.parent.messages()}
      listMessages={listParentMessages}
      markMessageRead={markParentMessageRead}
      testId="parent"
      emptyStateDescription="Broadcasts and DMs from the academy will show up here."
    />
  );
}
