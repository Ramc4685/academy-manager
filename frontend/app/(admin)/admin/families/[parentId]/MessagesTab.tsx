"use client";

import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { Button, Card, Chip, Overline, Skeleton } from "@/components/ds";
import { ErrorNotice } from "@/components/ds/error-notice";
import { listAdminUsers } from "@/lib/api/admin";
import {
  completeFamilyContactLog,
  fetchFamilyMessages,
  logFamilyContact,
  type FamilyMessage,
  type NewContactLog,
} from "@/lib/api/admin-family-crm";
import { getCurrentUser } from "@/lib/api/me";
import { formatInstantDay } from "@/lib/money";
import { queryKeys } from "@/lib/query/keys";

import {
  MAX_CONTACT_LOG_NOTE_LEN,
  channelLabel,
  contactNoteError,
  handoffHref,
  sourceLabel,
  statusLabel,
  statusVariant,
  warningText,
  type DirectChannel,
  type HandoffChannel,
} from "./family-messages";
import { staffName, staffOptions } from "./family-notes";

const inputClass =
  "w-full rounded-lg border border-rally-line bg-white px-3 py-2 text-sm text-rally-ink focus:outline-none focus:ring-2 focus:ring-rally-cobalt-600/30";

const HANDOFFS: ReadonlyArray<{ channel: HandoffChannel; label: string }> = [
  { channel: "whatsapp", label: "WhatsApp" },
  { channel: "sms", label: "SMS" },
  { channel: "email", label: "Email" },
];

const DIRECT: ReadonlyArray<{ channel: DirectChannel; label: string }> = [
  { channel: "call", label: "Log a call" },
  { channel: "in_person", label: "Log a talk in person" },
];

function errorText(error: unknown): string {
  return (error as Error | null)?.message || "Something went wrong. Try again.";
}

/**
 * The family Messages tab (People CRM spec §4, Phase 6): every email the app
 * sent this family with its delivery status, and the contacts staff logged
 * by hand, newest first. WhatsApp, SMS and email open the staff member's own
 * app; the app itself never sends SMS or WhatsApp ("Send from the app" is a
 * later phase and stays disabled).
 */
export function MessagesTab({
  parentId,
  phone,
  email,
}: {
  parentId: string;
  phone: string | null;
  email: string | null;
}) {
  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,2fr)]" data-testid="family-messages-tab">
      <ContactCard parentId={parentId} phone={phone} email={email} />
      <ThreadCard parentId={parentId} />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Contact: the handoff buttons and "log a contact"
// ---------------------------------------------------------------------------

function ContactCard({
  parentId,
  phone,
  email,
}: {
  parentId: string;
  phone: string | null;
  email: string | null;
}) {
  const qc = useQueryClient();
  const key = queryKeys.admin.familyMessages(parentId);
  // The handoff that was opened and waits for "Did you send it?".
  const [pending, setPending] = useState<HandoffChannel | null>(null);
  const [direct, setDirect] = useState<DirectChannel | null>(null);
  const [note, setNote] = useState("");
  const [noteError, setNoteError] = useState<string | null>(null);
  const [announcement, setAnnouncement] = useState("");
  // The control that opened the log form; focus returns there when the form
  // closes (saved, cancelled or "Not yet") so keyboard users are not dropped
  // on <body>. Falls back to the card heading when that control is gone.
  const returnFocus = useRef<HTMLElement | null>(null);
  const headingRef = useRef<HTMLDivElement | null>(null);
  const restoreFocus = useRef(false);

  const closeForm = () => {
    restoreFocus.current = true;
    setPending(null);
    setDirect(null);
    setNote("");
    setNoteError(null);
  };

  const log = useMutation({
    mutationFn: (payload: NewContactLog) => logFamilyContact(parentId, payload),
    onSuccess: (_data, payload) => {
      closeForm();
      setAnnouncement(
        payload.status === "logged"
          ? `${channelLabel(payload.channel)} logged.`
          : `${channelLabel(payload.channel)} saved as not sent yet.`,
      );
      void qc.invalidateQueries({ queryKey: key });
      void qc.invalidateQueries({ queryKey: queryKeys.admin.familyTimeline(parentId) });
    },
  });

  const save = (payload: NewContactLog) => {
    const problem = contactNoteError(note);
    setNoteError(problem);
    if (problem || log.isPending) return;
    log.mutate({ ...payload, note: note.trim() || null });
  };

  const channel = pending ?? direct;

  useEffect(() => {
    if (channel || !restoreFocus.current) return;
    restoreFocus.current = false;
    const target = returnFocus.current;
    (target && target.isConnected ? target : headingRef.current)?.focus();
  }, [channel]);

  return (
    <Card p={20} data-testid="family-messages-contact">
      <div
        ref={headingRef}
        tabIndex={-1}
        className="focus:outline-none"
        data-testid="family-messages-contact-heading"
      >
        <Overline>Contact this family</Overline>
      </div>
      <p role="status" className="sr-only" data-testid="family-contact-log-status">
        {announcement}
      </p>
      <p className="mt-1 text-xs text-rally-muted">
        Opens your own WhatsApp, messages or mail app. Log it here so the team sees it.
      </p>
      <div className="mt-3 flex flex-wrap gap-2">
        {HANDOFFS.map(({ channel: ch, label }) => {
          const href = handoffHref(ch, { phone, email });
          if (!href) {
            return (
              <Button
                key={ch}
                size="sm"
                variant="secondary"
                disabled
                data-testid={`family-handoff-${ch}`}
                title={ch === "email" ? "No email on file" : "No phone number on file"}
              >
                {label}
              </Button>
            );
          }
          return (
            <a
              key={ch}
              href={href}
              target={ch === "whatsapp" ? "_blank" : undefined}
              rel={ch === "whatsapp" ? "noopener noreferrer" : undefined}
              data-testid={`family-handoff-${ch}`}
              className="inline-flex min-h-9 items-center rounded-lg border border-rally-line bg-white px-3 text-sm font-medium text-rally-ink hover:bg-neutral-50 focus:outline-none focus:ring-2 focus:ring-rally-cobalt-600"
              onClick={(ev) => {
                returnFocus.current = ev.currentTarget;
                setAnnouncement("");
                setDirect(null);
                setPending(ch);
              }}
            >
              {label}
            </a>
          );
        })}
        <Button
          size="sm"
          variant="secondary"
          disabled
          data-testid="family-send-from-app"
          title="Sending from the app is coming in a later release"
        >
          Send from the app (coming)
        </Button>
      </div>
      <div className="mt-2 flex flex-wrap gap-2">
        {DIRECT.map(({ channel: ch, label }) => (
          <Button
            key={ch}
            size="sm"
            variant="secondary"
            data-testid={`family-log-${ch}`}
            onClick={(ev) => {
              returnFocus.current = ev.currentTarget;
              setAnnouncement("");
              setPending(null);
              setDirect(ch);
            }}
          >
            {label}
          </Button>
        ))}
      </div>

      {channel && (
        <div
          className="mt-4 space-y-2 rounded-lg border border-rally-line p-3"
          data-testid="family-contact-log-form"
          role="group"
          aria-labelledby="family-contact-log-title"
        >
          <p id="family-contact-log-title" className="text-sm font-medium text-rally-ink">
            {pending ? `Did you send the ${channelLabel(pending)}?` : `${channelLabel(channel)}: add a short note`}
          </p>
          <label htmlFor="family-contact-log-note" className="sr-only">
            Note
          </label>
          <textarea
            id="family-contact-log-note"
            data-testid="family-contact-log-note"
            className={`${inputClass} min-h-16`}
            placeholder={pending ? "What you sent (optional)" : "What you talked about (optional)"}
            maxLength={MAX_CONTACT_LOG_NOTE_LEN}
            value={note}
            aria-invalid={noteError ? true : undefined}
            aria-describedby={noteError || log.isError ? "family-contact-log-error" : undefined}
            onChange={(e) => setNote(e.target.value)}
          />
          {(noteError || log.isError) && (
            <p
              id="family-contact-log-error"
              role="alert"
              className="text-xs text-status-red-700"
              data-testid="family-contact-log-error"
            >
              {noteError ?? errorText(log.error)}
            </p>
          )}
          <div className="flex flex-wrap justify-end gap-2">
            {pending ? (
              <>
                <Button
                  size="sm"
                  variant="secondary"
                  disabled={log.isPending}
                  data-testid="family-contact-log-not-sent"
                  onClick={() => save({ channel: pending, status: "not_logged" })}
                >
                  Not yet
                </Button>
                <Button
                  size="sm"
                  disabled={log.isPending}
                  data-testid="family-contact-log-save"
                  onClick={() => save({ channel: pending, status: "logged" })}
                >
                  {log.isPending ? "Saving…" : "Yes, log it"}
                </Button>
              </>
            ) : (
              <>
                <Button
                  size="sm"
                  variant="secondary"
                  disabled={log.isPending}
                  data-testid="family-contact-log-cancel"
                  onClick={closeForm}
                >
                  Cancel
                </Button>
                <Button
                  size="sm"
                  disabled={log.isPending}
                  data-testid="family-contact-log-save"
                  onClick={() => direct && save({ channel: direct, status: "logged" })}
                >
                  {log.isPending ? "Saving…" : "Log it"}
                </Button>
              </>
            )}
          </div>
        </div>
      )}
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Thread
// ---------------------------------------------------------------------------

function ThreadCard({ parentId }: { parentId: string }) {
  const qc = useQueryClient();
  const key = queryKeys.admin.familyMessages(parentId);
  const messages = useQuery({ queryKey: key, queryFn: () => fetchFamilyMessages(parentId) });
  const staffQuery = useQuery({
    queryKey: queryKeys.admin.users("crm-staff"),
    queryFn: () => listAdminUsers(undefined, { roles: ["admin", "owner"] }),
    staleTime: 5 * 60_000,
  });
  const meQuery = useQuery({
    queryKey: queryKeys.admin.currentUser(),
    queryFn: getCurrentUser,
    staleTime: 5 * 60_000,
  });
  const staff = staffOptions(staffQuery.data?.users ?? []);
  const meId = meQuery.data?.user_id ?? null;
  // The row whose "Yes, I sent it" button just succeeded: once the refetch
  // removes that button, focus moves to the row itself instead of <body>.
  const [focusLogId, setFocusLogId] = useState<string | null>(null);
  const [announcement, setAnnouncement] = useState("");

  const complete = useMutation({
    mutationFn: (logId: string) => completeFamilyContactLog(parentId, logId),
    onSuccess: (_data, logId) => {
      setFocusLogId(logId);
      setAnnouncement("Marked as sent.");
      void qc.invalidateQueries({ queryKey: key });
      void qc.invalidateQueries({ queryKey: queryKeys.admin.familyTimeline(parentId) });
    },
  });

  if (messages.isLoading) {
    return (
      <Card p={20}>
        <Skeleton lines={5} />
      </Card>
    );
  }
  if (messages.isError || !messages.data) {
    return (
      <ErrorNotice
        testId="family-messages-error"
        message="Could not load this family's messages."
        onRetry={() => void messages.refetch()}
        retrying={messages.isFetching}
      />
    );
  }

  const entries = messages.data.entries;
  const warning = warningText(messages.data.warnings);

  return (
    <Card p={20} data-testid="family-messages">
      <Overline>Messages</Overline>
      <p role="status" className="sr-only" data-testid="family-messages-status">
        {announcement}
      </p>
      {warning && (
        <p className="mt-1 text-xs text-rally-muted" data-testid="family-messages-warnings">
          {warning}
        </p>
      )}
      {complete.isError && (
        <p role="alert" className="mt-1 text-xs text-status-red-700" data-testid="family-message-complete-error">
          {errorText(complete.error)}
        </p>
      )}
      {entries.length === 0 ? (
        <p className="mt-2 text-sm text-rally-muted" data-testid="family-messages-empty">
          No messages yet. Emails the academy sends and contacts you log show up here.
        </p>
      ) : (
        <ol className="mt-2 divide-y divide-rally-line" aria-live="polite" aria-relevant="additions">
          {entries.map((e) => (
            <MessageRow
              key={e.entry_id}
              entry={e}
              author={e.author_user_id ? staffName(staff, e.author_user_id, meId) : null}
              completing={complete.isPending && complete.variables === e.log_id}
              focusRequested={focusLogId !== null && focusLogId === e.log_id}
              onFocused={() => setFocusLogId(null)}
              onComplete={() => {
                if (!e.log_id) return;
                setAnnouncement("");
                complete.mutate(e.log_id);
              }}
            />
          ))}
        </ol>
      )}
    </Card>
  );
}

function MessageRow({
  entry,
  author,
  completing,
  focusRequested,
  onFocused,
  onComplete,
}: {
  entry: FamilyMessage;
  author: string | null;
  completing: boolean;
  focusRequested: boolean;
  onFocused: () => void;
  onComplete: () => void;
}) {
  const rowRef = useRef<HTMLLIElement | null>(null);
  useEffect(() => {
    // Wait for the refetch that removes the button before moving focus.
    if (!focusRequested || entry.can_complete) return;
    rowRef.current?.focus();
    onFocused();
  }, [focusRequested, entry.can_complete, onFocused]);

  return (
    <li
      ref={rowRef}
      tabIndex={-1}
      className="py-2 text-sm focus:outline-none focus-visible:ring-2 focus-visible:ring-rally-cobalt-600"
      data-testid={`family-message-${entry.source}`}
      data-status={entry.status}
      data-channel={entry.channel}
    >
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-mono text-xs text-rally-muted">{formatInstantDay(entry.at)}</span>
        <span className="text-xs uppercase tracking-wide text-rally-muted">
          {channelLabel(entry.channel)} · {sourceLabel(entry.source)}
        </span>
        <Chip variant={statusVariant(entry.status)} label={statusLabel(entry.status)} />
      </div>
      <p className="mt-0.5 font-medium text-rally-ink">{entry.summary}</p>
      {(entry.recipient || author) && (
        <p className="text-xs text-rally-muted">
          {[entry.recipient ? `To ${entry.recipient}` : null, author ? `By ${author}` : null]
            .filter(Boolean)
            .join(" · ")}
        </p>
      )}
      {entry.failed_reason && (
        <p className="text-xs text-status-red-700">Not delivered: {entry.failed_reason}</p>
      )}
      {entry.detail && (
        <p className="mt-0.5 whitespace-pre-line break-words text-rally-muted">{entry.detail}</p>
      )}
      {entry.can_complete && (
        <Button
          size="sm"
          variant="secondary"
          className="mt-1"
          disabled={completing}
          data-testid="family-message-complete"
          onClick={onComplete}
        >
          {completing ? "Saving…" : "Yes, I sent it"}
        </Button>
      )}
    </li>
  );
}
