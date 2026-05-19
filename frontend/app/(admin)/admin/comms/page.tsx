"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";

import {
  listAdminMessages,
  broadcastMessage,
  sendDm,
  type AdminMessageView,
} from "@/lib/api/admin";
import { queryKeys } from "@/lib/query/keys";

export default function AdminCommsPage() {
  const queryClient = useQueryClient();
  const [dmRecipientId, setDmRecipientId] = useState<string | null>(null);

  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: queryKeys.admin.messages(),
    queryFn: () => listAdminMessages(),
  });

  const messages = data?.messages ?? [];
  const broadcasts = messages.filter((m) => m.is_broadcast);
  const dms = messages.filter((m) => !m.is_broadcast);

  // Unique recipients for the DM thread list
  const dmThreads = Array.from(
    new Map(
      dms.map((m) => [m.recipient_id, m])
    ).values()
  );

  const invalidate = () =>
    queryClient.invalidateQueries({ queryKey: queryKeys.admin.messages() });

  // Selected DM thread messages
  const threadMessages = dmRecipientId
    ? dms.filter((m) => m.recipient_id === dmRecipientId)
    : [];

  return (
    <section data-testid="admin-comms">
      <h1 className="text-2xl font-semibold mb-6">Comms</h1>

      {isError && (
        <div
          role="alert"
          className="mb-4 rounded-md border border-red-200 bg-red-50 p-4 text-sm text-red-800 dark:border-red-900 dark:bg-red-950 dark:text-red-200"
        >
          <p>Failed to load messages.</p>
          <button
            onClick={() => void refetch()}
            className="mt-2 min-h-touch rounded-md border px-3"
          >
            Retry
          </button>
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Broadcast composer */}
        <div className="rounded-lg border border-neutral-200 dark:border-neutral-800 bg-white dark:bg-neutral-900 p-4">
          <h2 className="text-base font-semibold mb-3">Broadcast</h2>
          <BroadcastComposer onSent={invalidate} />

          <h3 className="mt-6 mb-2 text-sm font-semibold text-neutral-600 dark:text-neutral-400">
            Recent broadcasts
          </h3>
          {isLoading ? (
            <MessageSkeleton />
          ) : broadcasts.length === 0 ? (
            <p className="text-sm text-neutral-400">No broadcasts sent yet.</p>
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

        {/* DM thread list + composer */}
        <div className="rounded-lg border border-neutral-200 dark:border-neutral-800 bg-white dark:bg-neutral-900 p-4">
          <h2 className="text-base font-semibold mb-3">Direct messages</h2>

          {isLoading ? (
            <MessageSkeleton />
          ) : (
            <>
              {/* Thread list */}
              {dmThreads.length === 0 && !dmRecipientId && (
                <p className="text-sm text-neutral-400 mb-4">No DM threads yet.</p>
              )}
              <ul className="mb-4 space-y-1" data-testid="dm-thread-list">
                {dmThreads.map((m) => (
                  <li key={m.recipient_id}>
                    <button
                      onClick={() =>
                        setDmRecipientId(
                          m.recipient_id === dmRecipientId ? null : m.recipient_id
                        )
                      }
                      className={`w-full text-left min-h-touch px-3 rounded-md text-sm transition-colors ${
                        m.recipient_id === dmRecipientId
                          ? "bg-blue-50 text-blue-700 dark:bg-blue-950 dark:text-blue-300"
                          : "hover:bg-neutral-100 dark:hover:bg-neutral-800"
                      }`}
                    >
                      <span className="font-medium font-mono">
                        {m.recipient_id?.slice(0, 12)}…
                      </span>
                      <span className="ml-2 text-xs text-neutral-400">
                        {new Date(m.sent_at).toLocaleDateString()}
                      </span>
                    </button>
                  </li>
                ))}
              </ul>

              {/* Thread messages */}
              {dmRecipientId && (
                <>
                  <ul className="mb-4 space-y-2 max-h-64 overflow-y-auto" data-testid="dm-thread-messages">
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

              {/* New DM composer */}
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
        </div>
      </div>
    </section>
  );
}

// ---------------------------------------------------------------------------
// Broadcast composer
// ---------------------------------------------------------------------------

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

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!body.trim()) return;
    mutation.mutate();
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-2">
      {error && (
        <p role="alert" className="rounded-md bg-red-50 p-2 text-sm text-red-700 dark:bg-red-950 dark:text-red-300">
          {error}
        </p>
      )}
      <textarea
        required
        value={body}
        onChange={(e) => setBody(e.target.value)}
        placeholder="Write a message to all parents and students…"
        rows={3}
        className="w-full rounded-md border border-neutral-300 dark:border-neutral-700 bg-white dark:bg-neutral-900 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none"
        aria-label="Broadcast message body"
      />
      <div className="flex justify-end">
        <button
          type="submit"
          disabled={mutation.isPending || !body.trim()}
          className="min-h-touch rounded-md bg-blue-600 px-4 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-60"
        >
          {mutation.isPending ? "Sending…" : "Send broadcast"}
        </button>
      </div>
    </form>
  );
}

// ---------------------------------------------------------------------------
// DM composer (for an existing thread)
// ---------------------------------------------------------------------------

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

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!body.trim()) return;
    mutation.mutate();
  };

  return (
    <form onSubmit={handleSubmit} className="flex gap-2">
      {error && (
        <p role="alert" className="sr-only">
          {error}
        </p>
      )}
      <input
        type="text"
        value={body}
        onChange={(e) => setBody(e.target.value)}
        placeholder="Type a message…"
        className="flex-1 rounded-md border border-neutral-300 dark:border-neutral-700 bg-white dark:bg-neutral-900 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
        aria-label="DM message body"
      />
      <button
        type="submit"
        disabled={mutation.isPending || !body.trim()}
        className="min-h-touch rounded-md bg-blue-600 px-3 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-60"
      >
        Send
      </button>
    </form>
  );
}

// ---------------------------------------------------------------------------
// New DM composer (pick a recipient + write first message)
// ---------------------------------------------------------------------------

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

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!recipientId.trim() || !body.trim()) return;
    mutation.mutate();
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-2 border-t border-neutral-100 dark:border-neutral-800 pt-4">
      <p className="text-sm font-medium text-neutral-600 dark:text-neutral-400">New conversation</p>
      {error && (
        <p role="alert" className="rounded-md bg-red-50 p-2 text-sm text-red-700 dark:bg-red-950 dark:text-red-300">
          {error}
        </p>
      )}
      <input
        type="text"
        required
        value={recipientId}
        onChange={(e) => setRecipientId(e.target.value)}
        placeholder="Recipient user ID"
        className={inputClass}
        aria-label="Recipient user ID"
      />
      <textarea
        required
        value={body}
        onChange={(e) => setBody(e.target.value)}
        placeholder="Message…"
        rows={2}
        className="w-full rounded-md border border-neutral-300 dark:border-neutral-700 bg-white dark:bg-neutral-900 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none"
        aria-label="DM message"
      />
      <div className="flex justify-end">
        <button
          type="submit"
          disabled={mutation.isPending || !recipientId.trim() || !body.trim()}
          className="min-h-touch rounded-md bg-blue-600 px-4 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-60"
        >
          {mutation.isPending ? "Sending…" : "Send"}
        </button>
      </div>
    </form>
  );
}

// ---------------------------------------------------------------------------
// Message bubble
// ---------------------------------------------------------------------------

function MessageBubble({ message }: { message: AdminMessageView }) {
  return (
    <li className="rounded-md bg-neutral-50 dark:bg-neutral-800 px-3 py-2">
      <p className="text-sm">{message.body}</p>
      <p className="mt-1 text-xs text-neutral-400">
        {new Date(message.sent_at).toLocaleString()}
      </p>
    </li>
  );
}

const inputClass =
  "w-full rounded-md border border-neutral-300 dark:border-neutral-700 bg-white dark:bg-neutral-900 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500";

function MessageSkeleton() {
  return (
    <ul className="space-y-2">
      {[0, 1].map((i) => (
        <li key={i} className="h-12 animate-pulse rounded-md bg-neutral-100 dark:bg-neutral-800" />
      ))}
    </ul>
  );
}
