"use client";

/**
 * PersonaInbox — shared messages inbox view (UIM13).
 *
 * Coach and parent inboxes are the same read surface over the same shared
 * comms store, differing only in which BFF endpoints they call and which
 * query key they own. The persona pages are thin wrappers around this
 * component so the mark-read logic (and its optimistic-update semantics)
 * exists once rather than drifting between two near-identical files.
 */

import { useEffect, useMemo } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import type { InboxMessage, InboxMessagesResponse } from "@/lib/api/v2/messages";
import { Card } from "@/components/ds/card";
import { Skeleton } from "@/components/ds/skeleton";
import { EmptyState } from "@/components/ds/empty-state";

/** No push infra — polling is v1. Kept >= 30s per the UIM13 plan. */
const REFETCH_INTERVAL_MS = 30_000;

interface PersonaInboxProps {
  queryKey: readonly unknown[];
  listMessages: () => Promise<InboxMessagesResponse>;
  markMessageRead: (messageId: string) => Promise<unknown>;
  /** `<persona>-messages` / `<persona>-message-list` test ids. */
  testId: string;
  emptyStateDescription: string;
}

export function PersonaInbox({
  queryKey,
  listMessages,
  markMessageRead,
  testId,
  emptyStateDescription,
}: PersonaInboxProps) {
  const queryClient = useQueryClient();

  const { data, isLoading, isError, refetch } = useQuery({
    queryKey,
    queryFn: listMessages,
    refetchInterval: REFETCH_INTERVAL_MS,
  });

  const messages = data?.messages ?? [];
  const groups = useMemo(() => groupByDay(data?.messages ?? []), [data]);

  const setRead = (messageId: string, read: boolean) => {
    queryClient.setQueryData(queryKey, (old: InboxMessagesResponse | undefined) =>
      old
        ? {
            messages: old.messages.map((m) =>
              m.message_id === messageId ? { ...m, read } : m,
            ),
          }
        : old,
    );
  };

  const markRead = useMutation({
    mutationFn: (messageId: string) => markMessageRead(messageId),
    onMutate: async (messageId: string) => {
      await queryClient.cancelQueries({ queryKey });
      setRead(messageId, true);
    },
    // Roll back only the message that failed. The effect below fires one
    // mutation per unread message in the same tick, so restoring a whole
    // pre-batch snapshot here would clobber the sibling mutations that
    // succeeded.
    onError: (_err, messageId) => setRead(messageId, false),
  });

  // Mark unread messages read as they're viewed on this page. Keyed on the
  // set of ids rather than the messages themselves: the optimistic update
  // above flips `read` (not ids), so this cannot re-trigger itself. Re-firing
  // for an already-read message is harmless — the endpoint is an idempotent
  // `$addToSet`.
  const messageIds = messages.map((m) => m.message_id).join(",");
  useEffect(() => {
    for (const m of messages.filter((msg) => !msg.read)) {
      markRead.mutate(m.message_id);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [messageIds]);

  return (
    <section data-testid={`${testId}-messages`} className="space-y-4">
      <h1 className="text-lg font-semibold text-rally-ink">Messages</h1>

      {isError && (
        <Card p={16} style={{ borderColor: "#fecaca", background: "#fef2f2" }}>
          <div role="alert" className="flex items-center justify-between gap-3">
            <p className="text-sm text-red-800">Failed to load messages.</p>
            <button
              onClick={() => void refetch()}
              className="text-sm font-medium text-rally-cobalt"
            >
              Retry
            </button>
          </div>
        </Card>
      )}

      {isLoading ? (
        <Card p={16}>
          <Skeleton variant="line" lines={4} />
        </Card>
      ) : messages.length === 0 ? (
        <Card p={16}>
          <EmptyState title="No messages yet" description={emptyStateDescription} />
        </Card>
      ) : (
        <div className="space-y-5" data-testid={`${testId}-message-list`}>
          {groups.map(([day, dayMessages]) => (
            <div key={day} className="space-y-2">
              <h2 className="font-mono text-[10px] font-bold uppercase tracking-overline text-rally-muted">
                {day}
              </h2>
              <ul className="space-y-2">
                {dayMessages.map((m) => (
                  <MessageRow key={m.message_id} message={m} />
                ))}
              </ul>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

function MessageRow({ message }: { message: InboxMessage }) {
  const isAnnouncement = message.kind === "announcement";
  return (
    <li data-testid="message-row">
      <Card
        p={12}
        accent={isAnnouncement ? "#f59e0b" : "#2563eb"}
        className="flex items-start gap-2"
      >
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-xs font-semibold uppercase tracking-wide text-rally-subtle">
              {isAnnouncement ? "Announcement" : "Direct message"}
            </span>
            {!message.read && (
              <span
                data-testid="unread-dot"
                className="h-2 w-2 rounded-full bg-rally-cobalt"
                aria-label="Unread"
              />
            )}
          </div>
          <p className="mt-1 text-sm text-rally-ink">{message.body}</p>
          <p className="mt-1 text-[11px] text-rally-subtle">
            {new Date(message.created_at).toLocaleTimeString([], {
              hour: "numeric",
              minute: "2-digit",
            })}
          </p>
        </div>
      </Card>
    </li>
  );
}

function groupByDay(messages: InboxMessage[]): [string, InboxMessage[]][] {
  const sorted = [...messages].sort(
    (a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime(),
  );
  const groups = new Map<string, InboxMessage[]>();
  for (const m of sorted) {
    const day = new Date(m.created_at).toLocaleDateString(undefined, {
      weekday: "long",
      month: "short",
      day: "numeric",
    });
    const existing = groups.get(day);
    if (existing) {
      existing.push(m);
    } else {
      groups.set(day, [m]);
    }
  }
  return Array.from(groups.entries());
}
