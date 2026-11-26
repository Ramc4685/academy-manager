"use client";

/**
 * Admin messages.
 *
 * Preserves: broadcast composer, recent broadcasts list, DM thread list,
 * thread view, DM composer.
 *
 * `/admin/messages?dm=<parent_id>` opens the DM composer for that parent
 * (the Payments buckets "Message" action, spec §4), even when no thread with
 * them exists yet. An optional `&draft=<text>` prefills that composer (the
 * pathway dashboard's "Message parent" / "Offer a 1-on-1"); nothing is sent
 * until the admin presses Send.
 */

import type { Route } from "next";
import Link from "next/link";
import { Suspense, useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";

import {
  listAdminMessages,
  listAdminSessions,
  listAdminUsers,
  getAdminAcademy,
  broadcastMessage,
  markAdminMessageRead,
  sendDm,
  previewEmailCampaign,
  sendEmailCampaign,
  type AdminMessageView,
  type AdminSessionView,
  type AdminAcademyView,
  type CampaignAudiencePayload,
} from "@/lib/api/admin";
import type { ApiError } from "@/lib/api/client";
import { fetchFamilyRecord } from "@/lib/api/admin-families";
import { queryKeys } from "@/lib/query/keys";
import { formatAcademyDate, formatAcademyDateTime } from "@/lib/format/academy-time";
import { campaignAudienceLabel, type CampaignAudienceState } from "@/lib/format/campaign-audience";

import { CampaignRecipientReview } from "@/components/admin/campaign-recipient-review";
import { ConfirmActionDialog } from "@/components/ds/confirm-action-dialog";
import { DeliveryProblemsPanel } from "@/components/admin/delivery-problems-panel";
import { Avatar } from "@/components/ds/avatar";
import { Button } from "@/components/ds/button";
import { Card } from "@/components/ds/card";
import { Chip } from "@/components/ds/chip";
import { LaneHeader } from "@/components/ds/lane";

/** The three lanes on this page, in page order; ids double as fragment anchors. */
const MESSAGE_LANES = [
  { id: "direct", label: "Direct messages" },
  { id: "broadcast", label: "Broadcast" },
  { id: "campaign", label: "Email campaign" },
] as const;

export default function AdminMessagesPage() {
  return (
    <Suspense fallback={<section data-testid="admin-messages" className="space-y-5" />}>
      <AdminMessagesContent />
    </Suspense>
  );
}

function AdminMessagesContent() {
  const queryClient = useQueryClient();
  const searchParams = useSearchParams();
  const dmParam = searchParams.get("dm");
  const draftParam = searchParams.get("draft");
  const [dmRecipientId, setDmRecipientId] = useState<string | null>(dmParam);

  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: queryKeys.admin.messages(),
    queryFn: () => listAdminMessages(),
  });

  const messages = useMemo(() => data?.messages ?? [], [data]);
  const broadcasts = messages.filter((m) => m.is_broadcast);
  const dms = useMemo(() => messages.filter((m) => !m.is_broadcast), [messages]);

  // #841: every thread used to be titled "Direct conversation". The parent
  // directory is already an admin-visible read, so the family's name comes
  // from there rather than from a widened message DTO.
  // #892: the parent-role roster is not the whole academy. A family whose
  // contact is filed under another role — or any thread opened before that
  // roster lands — fell through to the literal word "Parent" while the
  // directory already knew the name. The directory read is the same
  // `listAdminUsers()` People search and the roles panel already make.
  const parentsQuery = useParents();
  const directoryQuery = useQuery({
    queryKey: queryKeys.admin.users(),
    queryFn: () => listAdminUsers(),
  });
  const nameById = useMemo(() => {
    const map = new Map<string, string>();
    for (const u of directoryQuery.data?.users ?? []) {
      if (u.display_name) map.set(u.user_id, u.display_name);
    }
    for (const u of parentsQuery.data?.users ?? []) {
      if (u.display_name) map.set(u.user_id, u.display_name);
    }
    return map;
  }, [directoryQuery.data, parentsQuery.data]);
  const nameFor = (userId: string | null): string =>
    (userId && nameById.get(userId)) || "Parent";

  const dmThreads = useMemo(() => buildDmThreads(dms), [dms]);

  const invalidate = () =>
    queryClient.invalidateQueries({ queryKey: queryKeys.admin.messages() });

  const threadMessages = dmRecipientId
    ? dms.filter((m) => counterpartyOf(m) === dmRecipientId)
    : [];

  // #864: opening a thread is what clears its unread marker, the same
  // mark-on-open the coach and parent inboxes already do. Only the messages
  // that are actually unread are sent, so re-opening a read thread is silent.
  const markRead = useMutation({
    mutationFn: async (messageIds: string[]) => {
      await Promise.all(messageIds.map((id) => markAdminMessageRead(id)));
    },
    onSuccess: invalidate,
  });

  const openThread = (counterpartyId: string) => setDmRecipientId(counterpartyId);

  // Marking read is driven by which thread is OPEN, not by the click that
  // opened it: `/admin/messages?dm=<parent_id>` (the Payments buckets
  // "Message" action) seeds the open thread without any click, and on desktop
  // the list stays beside it — so an unmarked thread would keep its dot while
  // the admin reads it. `markedRef` keeps this to one call per message id
  // while the refetch that clears `is_read` is still in flight.
  const markReadMutate = markRead.mutate;
  const markedRef = useRef<Set<string>>(new Set());
  useEffect(() => {
    if (!dmRecipientId) return;
    const unread =
      dmThreads.find((t) => t.counterpartyId === dmRecipientId)?.unreadIds ?? [];
    const fresh = unread.filter((id) => !markedRef.current.has(id));
    if (fresh.length === 0) return;
    for (const id of fresh) markedRef.current.add(id);
    markReadMutate(fresh);
  }, [dmRecipientId, dmThreads, markReadMutate]);

  return (
    <section data-testid="admin-messages" className="space-y-5">
      {/* Lane jump links: the page is three lanes long on a phone, and the
          sidebar entry cannot deep-link into the middle of it. */}
      <nav
        aria-label="Message lanes"
        className="flex flex-wrap gap-x-4 gap-y-1 text-sm"
        data-testid="admin-messages-lane-links"
      >
        {MESSAGE_LANES.map((lane) => (
          <a
            key={lane.id}
            href={`#${lane.id}`}
            className="inline-flex min-h-touch items-center font-medium text-rally-cobalt-700 hover:underline"
            data-testid={`admin-messages-lane-link-${lane.id}`}
          >
            {lane.label}
          </a>
        ))}
      </nav>
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

      {/* #864: Direct messages leads. A parent's unread reply is the thing an
          admin comes to this page for, and it used to sit below the whole
          broadcast composer and history — a long scroll away on a phone. */}
      {/* #893: an open thread takes the full content width. Nesting the
          list|thread pair inside one half of a two-column page left the open
          thread at roughly a quarter of a 1280px screen and pushed the
          composer's Send button out of its card. Broadcast drops below
          instead; it is not what the admin opened the thread to do. */}
      <div
        className={
          dmRecipientId ? "grid grid-cols-1 gap-5" : "grid grid-cols-1 lg:grid-cols-2 gap-5"
        }
      >
        <Card p={20} id="direct">
          <LaneHeader index="01" title="Direct messages" />

          {isLoading ? (
            <MessageSkeleton />
          ) : (
            <div
              className={
                dmRecipientId
                  // A fixed list track plus a `minmax(0,1fr)` thread track:
                  // an even split would shrink the thread again, and a
                  // `minmax(560px,…)` floor would overflow the card between
                  // `lg` and ~1200px. At 1280 the thread lands well past the
                  // 560px the issue asks for.
                  ? "lg:grid lg:grid-cols-[280px_minmax(0,1fr)] lg:gap-4 lg:items-start"
                  : undefined
              }
            >
              {/* List panel. On a phone an open thread replaces it; from `lg`
                  the two sit side by side. */}
              <div
                data-testid="dm-list-panel"
                className={dmRecipientId ? "hidden min-w-0 lg:block" : undefined}
              >
                {dmThreads.length === 0 && !dmRecipientId && (
                  <p className="text-sm text-rally-subtle mb-4">No DM threads yet.</p>
                )}
                <ul className="mb-4 space-y-1" data-testid="dm-thread-list">
                  {dmThreads.map((thread) => (
                    <DmThreadRow
                      key={thread.counterpartyId}
                      thread={thread}
                      name={nameFor(thread.counterpartyId)}
                      active={thread.counterpartyId === dmRecipientId}
                      onOpen={() => openThread(thread.counterpartyId)}
                      onClose={() => setDmRecipientId(null)}
                    />
                  ))}
                </ul>
                {!dmRecipientId && <NewConversationPicker onPick={openThread} />}
              </div>

              {dmRecipientId && (
                <div data-testid="dm-thread-panel" className="min-w-0">
                  <div className="mb-3 flex items-center gap-2">
                    <Button
                      variant="secondary"
                      size="sm"
                      data-testid="dm-back"
                      className="lg:hidden"
                      onClick={() => setDmRecipientId(null)}
                    >
                      ← Back
                    </Button>
                    <h3 className="truncate text-sm font-semibold text-rally-ink">
                      {nameFor(dmRecipientId)}
                    </h3>
                  </div>

                  <ThreadFamily parentId={dmRecipientId} />
                  {threadMessages.length === 0 && (
                    <p
                      className="mb-2 text-sm text-rally-subtle"
                      data-testid="dm-new-conversation"
                    >
                      New conversation — no messages with {nameFor(dmRecipientId)} yet.
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
                        <MessageBubble
                          key={m.message_id}
                          message={m}
                          threadParentId={dmRecipientId}
                          parentName={nameFor(dmRecipientId)}
                        />
                      ))}
                  </ul>
                  <DmComposer
                    recipientId={dmRecipientId}
                    initialBody={dmRecipientId === dmParam ? (draftParam ?? "") : ""}
                    onSent={invalidate}
                    key={dmRecipientId}
                  />
                </div>
              )}
            </div>
          )}
        </Card>

        <Card p={20} id="broadcast">
          <LaneHeader index="02" title="Broadcast" />
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
      </div>

      <Card p={20} id="campaign">
        <LaneHeader index="03" title="Email campaign" />
        <EmailCampaignComposer />
      </Card>

      <Card p={20} id="delivery-problems">
        <LaneHeader index="04" title="Delivery problems" />
        <DeliveryProblemsPanel />
      </Card>
    </section>
  );
}

/**
 * One conversation as the thread list renders it (#864).
 *
 * `latest` is what the row previews. `unreadIds` is what opening the row
 * marks read — the ids rather than a count, because the mark-read call is
 * per message.
 */
interface DmThread {
  counterpartyId: string;
  latest: AdminMessageView;
  unreadIds: string[];
}

/** D-18: the newest message came from the family, so the academy owes a reply.
 * Display state, not a business rule. */
function needsReply(thread: DmThread): boolean {
  return thread.latest.sender_id === thread.counterpartyId;
}

/**
 * D-18 (spec 3.4 a, b): the family's children and a link to the family
 * record. Reads the record the family page already uses; a coach or staff DM
 * has no family record, so nothing renders.
 */
function ThreadFamily({ parentId }: { parentId: string }) {
  const record = useQuery({
    queryKey: queryKeys.admin.familyRecord(parentId),
    queryFn: () => fetchFamilyRecord(parentId),
    retry: false,
  });
  const family = record.data?.family;
  if (!family) return null;
  const kids = family.children.map((c) => c.name).filter(Boolean);
  return (
    <div className="mb-3 flex flex-wrap items-center gap-x-3 text-[12px]" data-testid="dm-thread-family">
      {kids.length > 0 && <span className="text-rally-muted">{kids.join(", ")}</span>}
      <Link
        href={`/admin/families/${encodeURIComponent(record.data?.family_id ?? parentId)}`}
        className="inline-flex min-h-touch items-center font-medium text-rally-cobalt-700 hover:underline"
      >
        Open family →
      </Link>
    </div>
  );
}

/** The family a DM belongs to, whichever direction it travelled. */
function counterpartyOf(m: AdminMessageView): string | null {
  return m.counterparty_id ?? m.recipient_id;
}

function sentAtMs(m: AdminMessageView): number {
  return new Date(m.sent_at).getTime();
}

/**
 * Group DMs into conversations, newest conversation first.
 *
 * The previous one-liner (`new Map(dms.map((m) => [m.recipient_id, m]))`)
 * had two bugs behind it. A `Map` keeps the LAST write for a repeated key
 * and the API returns messages newest-first, so it kept each thread's
 * OLDEST message — which was only a slightly stale date until #864 put the
 * last message's text in the row, where it would have been plainly wrong.
 * And `recipient_id` is the admin on every message a family sends in, so
 * every inbound reply collapsed into one bogus thread.
 */
function buildDmThreads(dms: AdminMessageView[]): DmThread[] {
  const threads = new Map<string, DmThread>();
  for (const m of dms) {
    const counterpartyId = counterpartyOf(m);
    if (!counterpartyId) continue;
    const unread = m.is_read === false;
    const existing = threads.get(counterpartyId);
    if (!existing) {
      threads.set(counterpartyId, {
        counterpartyId,
        latest: m,
        unreadIds: unread ? [m.message_id] : [],
      });
      continue;
    }
    if (sentAtMs(m) > sentAtMs(existing.latest)) existing.latest = m;
    if (unread) existing.unreadIds.push(m.message_id);
  }
  return Array.from(threads.values()).sort(
    (a, b) => sentAtMs(b.latest) - sentAtMs(a.latest),
  );
}

/**
 * One row of the thread list: who, whether they are waiting on a reply, the
 * last thing said and when. Unread is never colour alone — the dot is
 * paired with a bolder name and text for a screen reader.
 */
function DmThreadRow({
  thread,
  name,
  active,
  onOpen,
  onClose,
}: {
  thread: DmThread;
  name: string;
  active: boolean;
  onOpen: () => void;
  onClose: () => void;
}) {
  const unreadCount = thread.unreadIds.length;
  return (
    <li>
      <button
        type="button"
        data-testid="dm-thread-row"
        aria-current={active ? "true" : undefined}
        onClick={active ? onClose : onOpen}
        className="w-full min-h-touch px-3 py-2 rounded-md text-left text-sm transition-colors"
        style={{
          background: active ? "var(--rally-cobalt-soft)" : "transparent",
          color: active ? "var(--rally-cobalt)" : "var(--rally-ink)",
        }}
      >
        <div className="flex items-center gap-2">
          <Avatar name={name} size={26} />
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2">
              <span
                className={`min-w-0 truncate text-sm ${
                  unreadCount > 0 ? "font-bold" : "font-semibold"
                }`}
              >
                {name}
              </span>
              {needsReply(thread) && (
                <span data-testid="dm-needs-reply" className="shrink-0">
                  <Chip variant="approval" label="NEEDS REPLY" />
                </span>
              )}
              {unreadCount > 0 && (
                <>
                  <span
                    data-testid="unread-dot"
                    aria-hidden="true"
                    className="h-2 w-2 shrink-0 rounded-full"
                    style={{ background: "var(--rally-cobalt)" }}
                  />
                  <span className="sr-only">
                    {unreadCount === 1 ? "1 unread message" : `${unreadCount} unread messages`}
                  </span>
                </>
              )}
              <span className="ml-auto shrink-0 font-mono text-[10px] text-rally-subtle">
                {formatAcademyDate(thread.latest.sent_at, null)}
              </span>
            </div>
            <div
              data-testid="dm-thread-preview"
              className={`truncate text-[12px] ${
                unreadCount > 0 ? "text-rally-ink" : "text-rally-subtle"
              }`}
            >
              {thread.latest.body}
            </div>
          </div>
        </div>
      </button>
    </li>
  );
}

/** The academy's parents. One query, shared by the audience counts, the DM
 * thread titles and the new-conversation picker. */
function useParents() {
  return useQuery({
    queryKey: queryKeys.admin.users("parent"),
    queryFn: () => listAdminUsers("parent"),
  });
}

/**
 * #838: both mass sends state who they reach before they go. The parent roster
 * is the audience for a whole-academy send, so its size is the recipient count.
 */
function useParentRecipientCount(): number | null {
  const query = useParents();
  return query.data ? query.data.users.length : null;
}

function recipientLabel(count: number | null): string {
  if (count === null) return "every parent in the academy";
  return count === 1 ? "1 parent" : `${count} parents`;
}

function BroadcastComposer({ onSent }: { onSent: () => void }) {
  const [body, setBody] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const recipientCount = useParentRecipientCount();

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
        setConfirmOpen(true);
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
          Audience: whole academy announcement — {recipientLabel(recipientCount)}.
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

      <ConfirmActionDialog
        open={confirmOpen}
        onOpenChange={setConfirmOpen}
        overline="Send broadcast"
        title={`Send this to ${recipientLabel(recipientCount)}?`}
        subject="Whole academy announcement"
        consequence={
          <>
            <p>
              Every parent in the academy sees it in their app inbox. It cannot be recalled or
              edited once sent.
            </p>
            <p className="font-semibold text-rally-ink">Preview</p>
            <p className="whitespace-pre-wrap rounded-md border border-rally-line bg-rally-paper px-3 py-2 text-rally-ink">
              {body.trim()}
            </p>
          </>
        }
        confirmLabel="Send broadcast"
        confirmVariant="primary"
        pending={mutation.isPending}
        onConfirm={() => {
          mutation.mutate();
          setConfirmOpen(false);
        }}
      />
    </form>
  );
}

function DmComposer({
  recipientId,
  initialBody,
  onSent,
}: {
  recipientId: string;
  initialBody: string;
  onSent: () => void;
}) {
  const [body, setBody] = useState(initialBody);
  const [error, setError] = useState<string | null>(null);

  const mutation = useMutation({
    meta: { success: "Reply sent." },
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
        if (!body.trim() || mutation.isPending) return;
        mutation.mutate();
      }}
      className="flex flex-wrap gap-2"
    >
      {error && (
        <p role="alert" className="basis-full text-sm font-medium text-status-red-800">
          {error}
        </p>
      )}
      {/* #893 `min-w-0`: an input's default `min-width: auto` is wider than a
          narrow thread column, which is what pushed Send out of its card. */}
      {/* A textarea so a prefilled draft can be read whole before sending;
          Enter still sends, as it did when this was a one-line input. */}
      <textarea
        rows={initialBody ? 4 : 1}
        value={body}
        onChange={(e) => setBody(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            e.currentTarget.form?.requestSubmit();
          }
        }}
        placeholder="Write a reply…"
        className="min-w-0 flex-1 rounded-md border border-rally-line bg-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-rally-cobalt-600/30"
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

/**
 * #841: this used to show admins an engineering note ("the current admin API
 * only accepts internal recipient references"). The parent directory was
 * always available to this page — it is what the broadcast audience count is
 * read from — so the picker is simply a search over it.
 */
function NewConversationPicker({ onPick }: { onPick: (parentId: string) => void }) {
  const [query, setQuery] = useState("");
  const { data, isLoading, isError } = useParents();
  const parents = data?.users ?? [];
  const needle = query.trim().toLowerCase();
  const matches = needle
    ? parents.filter(
        (u) =>
          u.display_name.toLowerCase().includes(needle) ||
          u.email.toLowerCase().includes(needle),
      )
    : parents;

  return (
    <div className="space-y-3 border-t border-rally-line/60 pt-4">
      <p className="font-mono text-[10px] font-bold uppercase tracking-overline text-rally-muted">
        New conversation
      </p>
      <input
        type="search"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        placeholder="Search families by name or email…"
        aria-label="Search families"
        data-testid="dm-recipient-search"
        className="w-full rounded-md border border-rally-line bg-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-rally-cobalt-600/30"
      />
      {isError ? (
        <p className="text-[12px] text-rally-subtle">
          Could not load families. Try again, or message a family from their profile.
        </p>
      ) : isLoading ? (
        <p className="text-[12px] text-rally-subtle">Loading families…</p>
      ) : matches.length === 0 ? (
        <p className="text-[12px] text-rally-subtle" data-testid="dm-recipient-empty">
          No family matches “{query.trim()}”.
        </p>
      ) : (
        <ul className="max-h-48 space-y-1 overflow-y-auto" data-testid="dm-recipient-list">
          {matches.slice(0, 25).map((u) => (
            <li key={u.user_id}>
              <button
                type="button"
                onClick={() => onPick(u.user_id)}
                className="flex w-full min-h-touch items-center gap-2 rounded-md px-3 py-2 text-left text-sm hover:bg-rally-paper"
              >
                <Avatar name={u.display_name} size={24} />
                <span className="min-w-0 flex-1">
                  <span className="block truncate font-medium text-rally-ink">
                    {u.display_name}
                  </span>
                  <span className="block truncate text-[12px] text-rally-subtle">{u.email}</span>
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/**
 * #841: sent and received used to look identical. Inside a thread with parent
 * `threadParentId`, anything that parent did not send is ours — no extra auth
 * lookup needed — so ours sits right on a tinted ground and theirs sits left
 * on paper. `threadParentId` is undefined in the broadcast list, where every
 * row is ours and the alignment would be noise.
 */
function MessageBubble({
  message,
  threadParentId,
  parentName,
}: {
  message: AdminMessageView;
  threadParentId?: string | null;
  parentName?: string;
}) {
  const fromParent = Boolean(threadParentId) && message.sender_id === threadParentId;
  const outbound = Boolean(threadParentId) && !fromParent;
  const who = message.is_broadcast
    ? `${message.scope_label ?? "Whole academy announcement"} · ${message.delivery_status ?? "recorded"}`
    : fromParent
      ? (parentName ?? "Parent")
      // D-18: any admin can answer a family, so a staff reply names its author.
      : (message.author_display_name ?? "You");

  return (
    <li className={outbound ? "flex justify-end" : "flex justify-start"}>
      <div
        className="max-w-[85%] rounded-md px-3 py-2"
        style={
          outbound
            ? { background: "var(--rally-cobalt-soft)", color: "var(--rally-ink)" }
            : { background: "var(--rally-paper)" }
        }
      >
        <p className="whitespace-pre-wrap text-sm text-rally-ink">{message.body}</p>
        <p className="mt-1 font-mono text-[10px] text-rally-subtle">
          {who} · {formatAcademyDateTime(message.sent_at, null)}
        </p>
        {message.scope_type === "cover_request" && message.scope_id ? (
          <Link
            href={`/admin?cover=${encodeURIComponent(message.scope_id)}` as Route}
            className="mt-2 inline-flex min-h-11 items-center text-sm font-semibold text-rally-cobalt underline"
            data-testid="admin-message-find-cover"
          >
            Find cover
          </Link>
        ) : null}
      </div>
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
  // #1030: one campaign can reach several sessions; the server sends one copy
  // per address across all of them.
  const [sessionIds, setSessionIds] = useState<string[]>([]);
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const [result, setResult] = useState<{
    sent: number;
    failed: number;
    total: number;
    queued: boolean;
  } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [confirmOpen, setConfirmOpen] = useState(false);
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

  const audience: CampaignAudiencePayload =
    audienceType === "session"
      ? { type: "session", session_ids: sessionIds }
      : { type: "academy", role: "parent" };
  const audienceChosen = audienceType === "academy" || sessionIds.length > 0;

  // #1029: the count comes from the server's resolution of this audience (the
  // same one the send uses), never from the session's enrolled-student count.
  const preview = useQuery({
    queryKey: queryKeys.admin.campaignPreview(audience),
    queryFn: () => previewEmailCampaign(audience),
    enabled: audienceChosen,
    // Send refetches before the dialog opens, so a focus refetch only flickers.
    refetchOnWindowFocus: false,
    staleTime: 30_000,
  });
  // A failed refetch must not leave a stale count on screen next to Send.
  const previewState: CampaignAudienceState = preview.isError
    ? { status: "error" }
    : preview.data
      ? { status: "ready", counts: preview.data }
      : { status: "loading" };

  const mutation = useMutation({
    mutationFn: () =>
      sendEmailCampaign({
        subject,
        body: buildEmailHtml(body, academy),
        audience,
        // #1031: the send is refused if the audience changed since this review.
        expected_audience_fingerprint: preview.data?.audience_fingerprint,
      }),
    onSuccess: (r) => {
      setResult({
        sent: r.sent_count,
        failed: r.failed_count,
        total: r.total_recipients,
        queued: r.queued ?? false,
      });
      setSubject("");
      setBody("");
      setError(null);
    },
    onError: (err: ApiError) => {
      if (err.status === 409 && err.details?.code === "audience_changed") {
        setError(
          "The audience changed since you reviewed it. Check the updated recipients and send again.",
        );
        void preview.refetch();
        return;
      }
      setError(err.message ?? "Failed to send campaign.");
    },
  });

  const canSend =
    !mutation.isPending &&
    subject.trim().length > 0 &&
    body.trim().length > 0 &&
    audienceChosen &&
    previewState.status === "ready" &&
    previewState.counts.recipient_count > 0;

  // #838: say who this reaches before it goes, in resolved addresses (#1029).
  const selectedSessions = sessions.filter((s) => sessionIds.includes(s.session_id));
  const audienceLabel =
    audienceType === "session"
      ? selectedSessions.length === 0
        ? "the selected sessions"
        : campaignAudienceLabel(
            previewState,
            selectedSessions.length === 1
              ? `on ${selectedSessions[0].title}`
              : `across ${selectedSessions.length} sessions`,
          )
      : campaignAudienceLabel(previewState, "in the academy");
  const toggleSession = (id: string) =>
    setSessionIds((ids) => (ids.includes(id) ? ids.filter((x) => x !== id) : [...ids, id]));

  if (result) {
    return (
      <div className="space-y-4">
        <div className="rounded-md border border-green-200 bg-green-50 p-4">
          <p className="font-semibold text-green-800">
            {result.queued ? "Campaign queued" : "Campaign sent!"}
          </p>
          <p className="mt-1 text-sm text-green-700">
            {result.queued ? (
              `Queued for ${result.total} · emails go out over the next few minutes`
            ) : (
              <>
                {result.sent} of {result.total} delivered
                {result.failed > 0 && ` · ${result.failed} failed`}
              </>
            )}
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
          <div className="space-y-2">
            <ul
              aria-label="Select sessions"
              className="max-h-56 divide-y divide-rally-line overflow-y-auto rounded-md border border-rally-line bg-white"
            >
              {sessions.length === 0 && (
                <li className="px-3 py-2 text-sm text-rally-subtle">No upcoming sessions.</li>
              )}
              {sessions.map((s) => (
                <li key={s.session_id}>
                  <label className="flex min-h-11 cursor-pointer items-center gap-3 px-3 py-2 text-sm">
                    <input
                      type="checkbox"
                      checked={sessionIds.includes(s.session_id)}
                      onChange={() => toggleSession(s.session_id)}
                      className="accent-rally-cobalt"
                      aria-label={s.title}
                    />
                    <span className="text-rally-ink">{s.title}</span>
                    {s.start_time && (
                      <span className="ml-auto font-mono text-[11px] text-rally-subtle">{s.start_time}</span>
                    )}
                  </label>
                </li>
              ))}
            </ul>
            <p className="text-[12px] text-rally-subtle" data-testid="campaign-selected-sessions">
              {selectedSessions.length === 0
                ? "Select one or more sessions."
                : `Selected: ${selectedSessions.map((s) => s.title).join(", ")}`}
            </p>
          </div>
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

      <div className="flex items-center justify-end gap-3">
        <p className="mr-auto text-[12px] text-rally-subtle">
          Audience: {audienceLabel}.
        </p>
        <Button
          type="button"
          variant="primary"
          size="sm"
          disabled={!canSend}
          onClick={() => {
            // Re-resolve so the review shows the audience as it is now (#1031).
            void preview.refetch();
            setConfirmOpen(true);
          }}
        >
          {mutation.isPending ? "Sending…" : "Send email"}
        </Button>
      </div>

      <ConfirmActionDialog
        open={confirmOpen}
        onOpenChange={setConfirmOpen}
        overline="Send email campaign"
        title={`Send to ${audienceLabel}?`}
        subject={subject.trim()}
        consequence={
          <>
            <p>
              A real email leaves the academy&apos;s address for every recipient. It cannot be
              recalled, edited or unsent, and bounces do not roll back the send.
            </p>
            {selectedSessions.length > 1 && (
              <p>
                <span className="font-semibold text-rally-ink">Sessions: </span>
                {selectedSessions.map((s) => s.title).join(", ")}
              </p>
            )}
            {preview.data && <CampaignRecipientReview preview={preview.data} />}
            <p className="font-semibold text-rally-ink">Preview</p>
            <p className="max-h-40 overflow-y-auto whitespace-pre-wrap rounded-md border border-rally-line bg-rally-paper px-3 py-2 text-rally-ink">
              {body.trim()}
            </p>
          </>
        }
        confirmLabel="Send email"
        confirmVariant="primary"
        pending={mutation.isPending}
        onConfirm={() => {
          mutation.mutate();
          setConfirmOpen(false);
        }}
      />
    </div>
  );
}
