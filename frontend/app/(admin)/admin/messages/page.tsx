"use client";

/**
 * Admin messages.
 *
 * Preserves: broadcast composer, recent broadcasts list, DM thread list,
 * thread view, DM composer.
 *
 * `/admin/messages?dm=<parent_id>` opens the DM composer for that parent
 * (the Payments buckets "Message" action, spec §4), even when no thread with
 * them exists yet.
 */

import { Suspense, useState } from "react";
import { useSearchParams } from "next/navigation";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";

import {
  listAdminMessages,
  listAdminSessions,
  getAdminAcademy,
  broadcastMessage,
  sendDm,
  sendEmailCampaign,
  type AdminMessageView,
  type AdminSessionView,
  type AdminAcademyView,
} from "@/lib/api/admin";
import { queryKeys } from "@/lib/query/keys";

import { Avatar } from "@/components/ds/avatar";
import { Button } from "@/components/ds/button";
import { Card } from "@/components/ds/card";
import { LaneHeader } from "@/components/ds/lane";

export default function AdminMessagesPage() {
  return (
    <Suspense fallback={<section data-testid="admin-messages" className="space-y-5" />}>
      <AdminMessagesContent />
    </Suspense>
  );
}

function AdminMessagesContent() {
  const queryClient = useQueryClient();
  const dmParam = useSearchParams().get("dm");
  const [dmRecipientId, setDmRecipientId] = useState<string | null>(dmParam);

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
            <Button variant="secondary" size="sm" onClick={() => void refetch()}>
              Retry
            </Button>
          </div>
        </Card>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
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
                          <Avatar name="Direct conversation" size={26} />
                          <div className="flex-1 min-w-0">
                            <div className="text-sm font-semibold truncate">
                              Direct conversation
                            </div>
                            <div className="text-[12px] text-rally-subtle">
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
                  {threadMessages.length === 0 && (
                    <p className="mb-2 text-sm text-rally-subtle" data-testid="dm-new-conversation">
                      New conversation — no messages with this family yet.
                    </p>
                  )}
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

              {!dmRecipientId && <NewConversationUnavailable />}
            </>
          )}
        </Card>
      </div>

      <Card p={20}>
        <LaneHeader index="03" title="Email campaign" />
        <EmailCampaignComposer />
      </Card>
    </section>
  );
}

function BroadcastComposer({ onSent }: { onSent: () => void }) {
  const [body, setBody] = useState("");
  const [error, setError] = useState<string | null>(null);

  const mutation = useMutation({
    mutationFn: () =>
      broadcastMessage({
        body,
        scope_type: "academy",
        scope_label: "Whole academy announcement",
      }),
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
        placeholder="Write an academy-wide announcement..."
        rows={3}
        className="w-full rounded-md border border-rally-line bg-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-rally-cobalt-600/30 resize-none"
        aria-label="Broadcast message body"
      />
      <div className="flex justify-end gap-3">
        <p className="mr-auto self-center text-[12px] text-rally-subtle">
          Audience: whole academy announcement.
        </p>
        <Button
          type="submit"
          variant="primary"
          size="sm"
          disabled={mutation.isPending || !body.trim()}
        >
          {mutation.isPending ? "Sending..." : "Send broadcast"}
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
        placeholder="Type a message..."
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

function NewConversationUnavailable() {
  return (
    <div className="space-y-3 border-t border-rally-line/60 pt-4">
      <p className="font-mono text-[10px] font-bold uppercase tracking-overline text-rally-muted">
        New conversation
      </p>
      <div className="rounded-md border border-dashed border-rally-line bg-rally-paper px-3 py-4">
        <p className="text-sm font-medium text-rally-ink">Recipient picker unavailable</p>
        <p className="mt-1 text-[12px] leading-5 text-rally-subtle">
          Starting a direct conversation requires a user-facing recipient picker. The
          current admin API only accepts internal recipient references, so new direct
          messages are disabled here until search or contact endpoints are available.
        </p>
        <div className="mt-3">
          <Button type="button" variant="secondary" size="sm" disabled>
            Choose recipient
          </Button>
        </div>
      </div>
    </div>
  );
}

function MessageBubble({ message }: { message: AdminMessageView }) {
  return (
    <li className="rounded-md bg-rally-paper px-3 py-2">
      <p className="text-sm text-rally-ink">{message.body}</p>
      <p className="mt-1 font-mono text-[10px] text-rally-subtle">
        {message.is_broadcast
          ? `${message.scope_label ?? "Whole academy announcement"} · ${message.delivery_status ?? "recorded"}`
          : "Direct conversation"}{" "}
        · {new Date(message.sent_at).toLocaleString()}
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

function escapeHtml(text: string): string {
  return text.replace(/[&<>"']/g, (ch) => {
    switch (ch) {
      case "&": return "&amp;";
      case "<": return "&lt;";
      case ">": return "&gt;";
      case '"': return "&quot;";
      case "'": return "&#039;";
      default: return ch;
    }
  });
}

function buildEmailHtml(body: string, academy: AdminAcademyView | undefined): string {
  const color = academy?.brand_color ?? "#1a56db";
  const name = escapeHtml(academy?.display_name ?? "Academy");
  const logo = academy?.logo_url;
  const safeLogo = logo && logo.startsWith("https://") ? logo : undefined;
  const lines = body.split("\n").map((l) => `<p style="margin:0 0 12px">${escapeHtml(l) || "&nbsp;"}</p>`).join("");
  return `<!DOCTYPE html><html><body style="margin:0;padding:0;font-family:sans-serif;background:#f9fafb">
<div style="max-width:600px;margin:0 auto;background:#ffffff;border-radius:8px;overflow:hidden">
  <div style="background:${color};padding:24px;text-align:center">
    ${safeLogo ? `<img src="${safeLogo}" alt="${name}" style="height:52px;margin-bottom:12px;display:block;margin-left:auto;margin-right:auto" />` : ""}
    <h1 style="margin:0;color:#ffffff;font-size:20px;font-weight:700">${name}</h1>
  </div>
  <div style="padding:28px 32px;color:#111827;font-size:15px;line-height:1.6">${lines}</div>
  <div style="padding:16px 32px;border-top:1px solid #e5e7eb;font-size:12px;color:#6b7280;text-align:center">
    You received this email because you are a member of ${name}.
  </div>
</div></body></html>`;
}

function EmailCampaignComposer() {
  const [audienceType, setAudienceType] = useState<"academy" | "session">("academy");
  const [sessionId, setSessionId] = useState("");
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const [result, setResult] = useState<{ sent: number; failed: number; total: number } | null>(null);
  const [error, setError] = useState<string | null>(null);

  const { data: academyData } = useQuery({
    queryKey: queryKeys.admin.academy(),
    queryFn: getAdminAcademy,
  });

  const { data: sessionsData } = useQuery({
    queryKey: queryKeys.admin.sessions(),
    queryFn: () => listAdminSessions(undefined, { window: "upcoming" }),
    enabled: audienceType === "session",
  });

  const sessions: AdminSessionView[] = sessionsData?.sessions ?? [];
  const academy: AdminAcademyView | undefined = academyData;
  const brandColor = academy?.brand_color ?? "#1a56db";

  const mutation = useMutation({
    mutationFn: () =>
      sendEmailCampaign({
        subject,
        body: buildEmailHtml(body, academy),
        audience:
          audienceType === "session"
            ? { type: "session", session_id: sessionId }
            : { type: "academy", role: "parent" },
      }),
    onSuccess: (r) => {
      setResult({ sent: r.sent_count, failed: r.failed_count, total: r.total_recipients });
      setSubject("");
      setBody("");
      setError(null);
    },
    onError: (err: Error) => {
      setError(err.message ?? "Failed to send campaign.");
    },
  });

  const canSend =
    !mutation.isPending &&
    subject.trim().length > 0 &&
    body.trim().length > 0 &&
    (audienceType === "academy" || sessionId.length > 0);

  if (result) {
    return (
      <div className="space-y-4">
        <div className="rounded-md border border-green-200 bg-green-50 p-4">
          <p className="font-semibold text-green-800">Campaign sent!</p>
          <p className="mt-1 text-sm text-green-700">
            {result.sent} of {result.total} delivered
            {result.failed > 0 && ` · ${result.failed} failed`}
          </p>
        </div>
        <Button variant="secondary" size="sm" onClick={() => setResult(null)}>
          Send another
        </Button>
      </div>
    );
  }

  return (
    <div className="space-y-5">
      {/* Academy branding preview */}
      <div
        className="flex items-center gap-3 rounded-md px-4 py-3"
        style={{ background: brandColor }}
      >
        {academy?.logo_url && (
          <img src={academy.logo_url} alt={academy.display_name} className="h-8 w-auto object-contain" />
        )}
        <span className="font-semibold text-white text-sm">
          {academy?.display_name ?? "Loading academy…"}
        </span>
        <span className="ml-auto text-xs text-white/70">Email header preview</span>
      </div>

      {/* Audience */}
      <fieldset className="space-y-2">
        <legend className="font-mono text-[10px] font-bold uppercase tracking-overline text-rally-muted">
          Audience
        </legend>
        <div className="flex gap-4">
          <label className="flex items-center gap-2 cursor-pointer text-sm">
            <input
              type="radio"
              name="audience"
              value="academy"
              checked={audienceType === "academy"}
              onChange={() => setAudienceType("academy")}
              className="accent-rally-cobalt"
            />
            All parents
          </label>
          <label className="flex items-center gap-2 cursor-pointer text-sm">
            <input
              type="radio"
              name="audience"
              value="session"
              checked={audienceType === "session"}
              onChange={() => setAudienceType("session")}
              className="accent-rally-cobalt"
            />
            By session
          </label>
        </div>

        {audienceType === "session" && (
          <select
            value={sessionId}
            onChange={(e) => setSessionId(e.target.value)}
            className="w-full rounded-md border border-rally-line bg-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-rally-cobalt-600/30"
            aria-label="Select session"
          >
            <option value="">— Select a session —</option>
            {sessions.map((s) => (
              <option key={s.session_id} value={s.session_id}>
                {s.title} {s.start_time ? `· ${s.start_time}` : ""}
              </option>
            ))}
          </select>
        )}
      </fieldset>

      {/* Subject */}
      <div className="space-y-1">
        <label className="font-mono text-[10px] font-bold uppercase tracking-overline text-rally-muted">
          Subject
        </label>
        <input
          type="text"
          value={subject}
          onChange={(e) => setSubject(e.target.value)}
          placeholder="e.g. Introducing your parent portal"
          className="w-full rounded-md border border-rally-line bg-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-rally-cobalt-600/30"
          aria-label="Email subject"
        />
      </div>

      {/* Body */}
      <div className="space-y-1">
        <label className="font-mono text-[10px] font-bold uppercase tracking-overline text-rally-muted">
          Message body
        </label>
        <textarea
          value={body}
          onChange={(e) => setBody(e.target.value)}
          placeholder="Write your message here. Use blank lines to separate paragraphs."
          rows={7}
          className="w-full rounded-md border border-rally-line bg-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-rally-cobalt-600/30 resize-none"
          aria-label="Email body"
        />
        <p className="text-[11px] text-rally-subtle">
          Your academy logo and brand color are added automatically to the email header.
        </p>
      </div>

      {error && (
        <p role="alert" className="rounded-md bg-red-50 p-2 text-sm text-red-700">
          {error}
        </p>
      )}

      <div className="flex justify-end">
        <Button
          type="button"
          variant="primary"
          size="sm"
          disabled={!canSend}
          onClick={() => mutation.mutate()}
        >
          {mutation.isPending ? "Sending…" : "Send email"}
        </Button>
      </div>
    </div>
  );
}
