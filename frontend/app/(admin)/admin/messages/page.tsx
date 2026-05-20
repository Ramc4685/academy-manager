"use client";

/**
 * Admin messages — Rally restyle.
 *
 * Backend BFF path stays at /admin/messages/*.
 * Preserves: broadcast composer, recent broadcasts list, DM thread list,
 * thread view, DM composer, new-DM composer.
 */

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";

import {
  listAdminMessages,
  broadcastMessage,
  sendDm,
  type AdminMessageView,
} from "@/lib/api/admin";
import { queryKeys } from "@/lib/query/keys";

import { Avatar } from "@/components/ds/avatar";
import { Button } from "@/components/ds/button";
import { Card } from "@/components/ds/card";
import { LaneHeader } from "@/components/ds/lane";

export default function AdminMessagesPage() {
  const queryClient = useQueryClient();
  const [dmRecipientId, setDmRecipientId] = useState<string | null>(null);

  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: queryKeys.admin.messages(),
    queryFn: () => listAdminMessages(),
  });

  const messages = data?.messages ?? [];
  const broadcasts = messages.filter((m) => m.is_broadcast);
  const dms = messages.filter((m) => !m.is_broadcast);

  const dmThreads = Array.from(new Map(dms.map((m) => [m.recipient_id, m])).values());

  const invalidate = () =>
    queryClient.invalidateQueries({ queryKey: queryKeys.admin.messages() });

  const threadMessages = dmRecipientId
    ? dms.filter((m) => m.recipient_id === dmRecipientId)
    : [];

  return (
    <section data-testid="admin-messages" className="space-y-5">
      {isError && (
        <Card p={16} style={{ borderColor: "#fecaca", background: "#fef2f2" }}>
          <div role="alert" className="flex items-center justify-between gap-3">
            <p className="text-sm text-red-800">Failed to load messages.</p>
            <Button variant="secondary" size="sm" onClick={() => void refetch()}>Retry</Button>
          </div>
        </Card>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
        {/* Broadcast panel */}
        <Card p={20}>
          <LaneHeader index="01" title="Broadcast" />
          <BroadcastComposer onSent={invalidate} />
          <div className="mt-6">
            <h3 className="mb-2 font-mono text-[10px] font-bold uppercase tracking-overline text-rally-muted">
              Recent broadcasts
            </h3>
            {isLoading ? (
              <MessageSkeleton />
            ) : broadcasts.length === 0 ? (
              <p className="text-sm text-rally-subtle">No broadcasts sent yet.</p>
            ) : (
              <ul className="space-y-2" data-testid="broadcast-list">
                {broadcasts
                  .slice()
                  .sort((a, b) => new Date(b.sent_at).getTime() - new Date(a.sent_at).getTime())
                  .slice(0, 10)
                  .map((m) => (
                    <MessageBubble key={m.message_id} message={m} />
                  ))}
              </ul>
            )}
          </div>
        </Card>

        {/* DM panel */}
        <Card p={20}>
          <LaneHeader index="02" title="Direct messages" />

          {isLoading ? (
            <MessageSkeleton />
          ) : (
            <>
              {dmThreads.length === 0 && !dmRecipientId && (
                <p className="text-sm text-rally-subtle mb-4">No DM threads yet.</p>
              )}
              <ul className="mb-4 space-y-1" data-testid="dm-thread-list">
                {dmThreads.map((m) => {
                  const active = m.recipient_id === dmRecipientId;
                  return (
                    <li key={m.recipient_id}>
                      <button
                        onClick={() =>
                          setDmRecipientId(active ? null : m.recipient_id)
                        }
                        className="w-full min-h-touch px-3 py-2 rounded-md text-left text-sm transition-colors"
                        style={{
                          background: active ? "var(--rally-cobalt-soft)" : "transparent",
                          color: active ? "var(--rally-cobalt)" : "var(--rally-ink)",
                        }}
                      >
                        <div className="flex items-center gap-2">
                          <Avatar name={m.recipient_id ?? "?"} size={26} />
                          <div className="flex-1 min-w-0">
                            <div className="font-mono text-xs font-semibold truncate">
                              {m.recipient_id?.slice(0, 12)}…
                            </div>
                            <div className="font-mono text-[10px] text-rally-subtle">
                              {new Date(m.sent_at).toLocaleDateString()}
                            </div>
                          </div>
                        </div>
                      </button>
                    </li>
                  );
                })}
              </ul>

              {dmRecipientId && (
                <>
                  <ul
                    className="mb-4 space-y-2 max-h-64 overflow-y-auto"
                    data-testid="dm-thread-messages"
                  >
                    {threadMessages
                      .slice()
                      .sort(
                        (a, b) => new Date(a.sent_at).getTime() - new Date(b.sent_at).getTime()
                      )
                      .map((m) => (
                        <MessageBubble key={m.message_id} message={m} />
                      ))}
                  </ul>
                  <DmComposer
                    recipientId={dmRecipientId}
                    onSent={invalidate}
                    key={dmRecipientId}
                  />
                </>
              )}

              {!dmRecipientId && (
                <NewDmComposer
                  onSent={(recipientId) => {
                    setDmRecipientId(recipientId);
                    invalidate();
                  }}
                />
              )}
            </>
          )}
        </Card>
      </div>
    </section>
  );
}

// ─────────────────────────────────────────────────────────────────────────────

function BroadcastComposer({ onSent }: { onSent: () => void }) {
  const [body, setBody] = useState("");
  const [error, setError] = useState<string | null>(null);

  const mutation = useMutation({
    mutationFn: () => broadcastMessage({ body }),
    onSuccess: () => {
      setBody("");
      setError(null);
      onSent();
    },
    onError: (err: Error) => {
      setError(err.message ?? "Failed to send broadcast.");
    },
  });

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        if (!body.trim()) return;
        mutation.mutate();
      }}
      className="space-y-2"
    >
      {error && (
        <p role="alert" className="rounded-md bg-red-50 p-2 text-sm text-red-700">
          {error}
        </p>
      )}
      <textarea
        required
        value={body}
        onChange={(e) => setBody(e.target.value)}
        placeholder="Write a message to all parents and students…"
        rows={3}
        className="w-full rounded-md border border-rally-line bg-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-rally-cobalt-600/30 resize-none"
        aria-label="Broadcast message body"
      />
      <div className="flex justify-end">
        <Button
          type="submit"
          variant="primary"
          size="sm"
          disabled={mutation.isPending || !body.trim()}
        >
          {mutation.isPending ? "Sending…" : "Send broadcast"}
        </Button>
      </div>
    </form>
  );
}

function DmComposer({
  recipientId,
  onSent,
}: {
  recipientId: string;
  onSent: () => void;
}) {
  const [body, setBody] = useState("");
  const [error, setError] = useState<string | null>(null);

  const mutation = useMutation({
    mutationFn: () => sendDm({ recipient_id: recipientId, body }),
    onSuccess: () => {
      setBody("");
      setError(null);
      onSent();
    },
    onError: (err: Error) => {
      setError(err.message ?? "Failed to send message.");
    },
  });

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        if (!body.trim()) return;
        mutation.mutate();
      }}
      className="flex gap-2"
    >
      {error && <p role="alert" className="sr-only">{error}</p>}
      <input
        type="text"
        value={body}
        onChange={(e) => setBody(e.target.value)}
        placeholder="Type a message…"
        className="flex-1 rounded-md border border-rally-line bg-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-rally-cobalt-600/30"
        aria-label="DM message body"
      />
      <Button
        type="submit"
        variant="primary"
        size="sm"
        disabled={mutation.isPending || !body.trim()}
      >
        Send
      </Button>
    </form>
  );
}

function NewDmComposer({ onSent }: { onSent: (recipientId: string) => void }) {
  const [recipientId, setRecipientId] = useState("");
  const [body, setBody] = useState("");
  const [error, setError] = useState<string | null>(null);

  const mutation = useMutation({
    mutationFn: () => sendDm({ recipient_id: recipientId, body }),
    onSuccess: () => {
      setBody("");
      setError(null);
      onSent(recipientId);
    },
    onError: (err: Error) => {
      setError(err.message ?? "Failed to send DM.");
    },
  });

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        if (!recipientId.trim() || !body.trim()) return;
        mutation.mutate();
      }}
      className="space-y-2 border-t border-rally-line/60 pt-4"
    >
      <p className="font-mono text-[10px] font-bold uppercase tracking-overline text-rally-muted">
        New conversation
      </p>
      {error && (
        <p role="alert" className="rounded-md bg-red-50 p-2 text-sm text-red-700">
          {error}
        </p>
      )}
      <input
        type="text"
        required
        value={recipientId}
        onChange={(e) => setRecipientId(e.target.value)}
        placeholder="Recipient user ID"
        className="w-full rounded-md border border-rally-line bg-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-rally-cobalt-600/30"
        aria-label="Recipient user ID"
      />
      <textarea
        required
        value={body}
        onChange={(e) => setBody(e.target.value)}
        placeholder="Message…"
        rows={2}
        className="w-full rounded-md border border-rally-line bg-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-rally-cobalt-600/30 resize-none"
        aria-label="DM message"
      />
      <div className="flex justify-end">
        <Button
          type="submit"
          variant="primary"
          size="sm"
          disabled={mutation.isPending || !recipientId.trim() || !body.trim()}
        >
          {mutation.isPending ? "Sending…" : "Send"}
        </Button>
      </div>
    </form>
  );
}

function MessageBubble({ message }: { message: AdminMessageView }) {
  return (
    <li className="rounded-md bg-rally-paper px-3 py-2">
      <p className="text-sm text-rally-ink">{message.body}</p>
      <p className="mt-1 font-mono text-[10px] text-rally-subtle">
        {new Date(message.sent_at).toLocaleString()}
      </p>
    </li>
  );
}

function MessageSkeleton() {
  return (
    <ul className="space-y-2">
      {[0, 1].map((i) => (
        <li key={i} className="h-12 animate-pulse rounded-md bg-rally-line/40" />
      ))}
    </ul>
  );
}
