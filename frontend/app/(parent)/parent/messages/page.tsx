"use client";

import { useQuery } from "@tanstack/react-query";

import { AcademyThread } from "@/components/messages/academy-thread";
import { PersonaInbox } from "@/components/messages/PersonaInbox";
import { getParentAcademy } from "@/lib/api/parent";
import { listParentMessages, markParentMessageRead } from "@/lib/api/v2/messages";
import { queryKeys } from "@/lib/query/keys";

export default function ParentMessagesPage() {
  const academy = useQuery({ queryKey: queryKeys.parent.academy(), queryFn: getParentAcademy });
  return (
    <PersonaInbox
      queryKey={queryKeys.parent.messages()}
      listMessages={listParentMessages}
      markMessageRead={markParentMessageRead}
      testId="parent"
      emptyStateTitle="No announcements yet."
      emptyStateDescription="Announcements from the academy will show up here."
      excludeDirect
      renderThread={({ messages, isLoading, isError }) =>
        // A failed load hides the composer; the inbox shows its Retry.
        isError ? null : (
          <AcademyThread
            messages={messages}
            isLoading={isLoading}
            academyName={academy.data?.display_name || "the academy"}
            academyPhone={academy.data?.contact_phone}
            academyTimezone={academy.data?.timezone}
            queryKey={queryKeys.parent.messages()}
          />
        )
      }
    />
  );
}
