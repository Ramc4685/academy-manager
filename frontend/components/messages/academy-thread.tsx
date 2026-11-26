"use client";

/**
 * "Message the academy" (D-18, spec docs/design/parent-messaging.md).
 *
 * The parent's one thread with the academy: their messages on the right,
 * replies on the left under the academy's name (never a staff member's), and
 * a composer. The bubble appears only once the server has accepted the
 * message: a message that silently failed is worse than a short wait.
 */

import { useEffect, useRef, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { Button } from "@/components/ds/button";
import { Card } from "@/components/ds/card";
import { Skeleton } from "@/components/ds/skeleton";
import { Overline } from "@/components/ds/typography";
import type { ApiError } from "@/lib/api/client";
import { telHref } from "@/lib/contact-links";
import { formatInAcademyZone } from "@/lib/format/academy-time";
import {
  sendParentMessage,
  type InboxMessage,
  type InboxMessagesResponse,
} from "@/lib/api/v2/messages";

export const ACADEMY_MESSAGE_MAX = 1000;
/** Messages shown before "Show earlier messages". */
export const THREAD_PAGE = 20;
const RATE_LIMIT_COOLDOWN_MS = 60_000;

/** The thread: direct messages only, oldest first. */
export function threadMessages(messages: InboxMessage[]): InboxMessage[] {
  return messages
    .filter((m) => m.kind === "dm")
    .sort((a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime());
}

export function composerState(body: string) {
  const count = body.length;
  const tooLong = count > ACADEMY_MESSAGE_MAX;
  return { count, tooLong, canSend: body.trim().length > 0 && !tooLong };
}

export function sendErrorText(error: unknown, phone: string | null | undefined): string {
  if ((error as ApiError | undefined)?.status === 429) {
    return phone
      ? `You have sent a lot of messages in a short time. Please wait a little, or call ${phone}.`
      : "You have sent a lot of messages in a short time. Please wait a little.";
  }
  return "Your message was not sent. Check your connection and try again.";
}

export interface AcademyThreadProps {
  messages: InboxMessage[];
  isLoading: boolean;
  academyName: string;
  academyPhone?: string | null;
  academyTimezone?: string | null;
  /** The inbox query the sent message is appended to. */
  queryKey: readonly unknown[];
}

export function AcademyThread({
  messages,
  isLoading,
  academyName,
  academyPhone,
  academyTimezone,
  queryKey,
}: AcademyThreadProps) {
  const queryClient = useQueryClient();
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const [body, setBody] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [cooldown, setCooldown] = useState(false);
  const [showAll, setShowAll] = useState(false);

  const thread = threadMessages(messages);
  const shown = showAll ? thread : thread.slice(-THREAD_PAGE);
  const { count, tooLong, canSend } = composerState(body);

  // Announce a reply that arrives on the 30-second poll, not on first load.
  const replies = thread.filter((m) => !m.mine).length;
  const seenReplies = useRef<number | null>(null);
  const [announce, setAnnounce] = useState("");
  useEffect(() => {
    if (isLoading) return;
    if (seenReplies.current !== null && replies > seenReplies.current) {
      setAnnounce(`New reply from ${academyName}`);
    }
    seenReplies.current = replies;
  }, [replies, isLoading, academyName]);

  useEffect(() => {
    if (!cooldown) return;
    const t = setTimeout(() => setCooldown(false), RATE_LIMIT_COOLDOWN_MS);
    return () => clearTimeout(t);
  }, [cooldown]);

  const send = useMutation({
    meta: { success: `Message sent to ${academyName}.` },
    mutationFn: () => sendParentMessage(body),
    onSuccess: (sent) => {
      queryClient.setQueryData(queryKey, (old: InboxMessagesResponse | undefined) =>
        old ? { messages: [sent, ...old.messages] } : { messages: [sent] },
      );
      setBody("");
      setError(null);
      textareaRef.current?.focus();
    },
    onError: (err) => {
      setError(sendErrorText(err, academyPhone));
      if ((err as ApiError).status === 429) setCooldown(true);
    },
  });

  const submit = () => {
    if (!canSend || send.isPending || cooldown) return;
    send.mutate();
  };

  const tel = telHref(academyPhone);
  const errorId = "academy-message-error";
  const counterId = "academy-message-count";

  return (
    <Card p={16} id="academy" data-testid="academy-thread">
      <Overline>Message the academy</Overline>
      <p className="mt-1 text-[13px] text-rally-muted">
        The front desk reads these.
        {tel && (
          <>
            {" "}For anything urgent today, call{" "}
            <a
              href={tel}
              className="inline-flex min-h-touch items-center font-medium text-rally-cobalt-700 underline underline-offset-2"
            >
              {academyPhone}
            </a>
            .
          </>
        )}
      </p>

      {isLoading ? (
        <div className="mt-3">
          <Skeleton variant="line" lines={3} />
        </div>
      ) : thread.length === 0 ? (
        <p className="mt-3 text-sm text-rally-muted" data-testid="academy-thread-empty">
          Ask a question or tell us something. Your message and the reply stay here.
        </p>
      ) : (
        <>
          {thread.length > shown.length && (
            <button
              type="button"
              onClick={() => setShowAll(true)}
              className="mt-3 min-h-touch text-sm font-medium text-rally-cobalt-700"
            >
              Show earlier messages
            </button>
          )}
          <ol
            aria-label={`Messages with ${academyName}`}
            className="mt-3 space-y-2"
            data-testid="academy-thread-messages"
          >
            {shown.map((m) => (
              <ThreadBubble
                key={m.message_id}
                message={m}
                academyName={academyName}
                academyTimezone={academyTimezone}
              />
            ))}
          </ol>
        </>
      )}
      <p className="sr-only" aria-live="polite">
        {announce}
      </p>

      <form
        className="mt-3"
        onSubmit={(e) => {
          e.preventDefault();
          submit();
        }}
      >
        <label htmlFor="academy-message-body" className="sr-only">
          Message to the academy
        </label>
        <textarea
          id="academy-message-body"
          ref={textareaRef}
          rows={3}
          value={body}
          readOnly={send.isPending}
          disabled={isLoading}
          onChange={(e) => setBody(e.target.value)}
          onKeyDown={(e) => {
            // Enter is a new line; Ctrl/Cmd+Enter sends on a keyboard.
            if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
              e.preventDefault();
              submit();
            }
          }}
          placeholder="Write a message…"
          aria-describedby={error ? `${counterId} ${errorId}` : counterId}
          aria-invalid={tooLong || undefined}
          className="field-sizing-content max-h-40 min-h-[4.5rem] w-full rounded-md border border-rally-line bg-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-rally-cobalt-600/30"
          data-testid="academy-message-input"
        />
        {error && (
          <p id={errorId} role="alert" className="mt-1 text-sm font-medium text-status-red-800">
            {error}
          </p>
        )}
        {tooLong && (
          <p role="alert" className="mt-1 text-sm font-medium text-status-red-800">
            Messages can be up to {ACADEMY_MESSAGE_MAX} characters.
          </p>
        )}
        <div className="mt-2 flex items-center justify-between gap-3">
          <span
            id={counterId}
            className={`font-mono text-[11px] ${tooLong ? "font-bold text-status-red-800" : "text-rally-subtle"}`}
          >
            {count} / {ACADEMY_MESSAGE_MAX}
          </span>
          <Button
            type="submit"
            variant="primary"
            size="lg"
            disabled={!canSend || send.isPending || cooldown || isLoading}
            data-testid="academy-message-send"
          >
            {send.isPending ? "Sending…" : "Send"}
          </Button>
        </div>
      </form>
    </Card>
  );
}

function ThreadBubble({
  message,
  academyName,
  academyTimezone,
}: {
  message: InboxMessage;
  academyName: string;
  academyTimezone?: string | null;
}) {
  const mine = Boolean(message.mine);
  const time = formatInAcademyZone(message.created_at, academyTimezone, {
    hour: "numeric",
    minute: "2-digit",
  });
  const who = mine ? "You" : academyName;
  return (
    <li className={mine ? "flex justify-end" : "flex justify-start"} data-testid="academy-bubble">
      <div
        className={`max-w-[85%] rounded-md px-3 py-2 md:max-w-[70%] ${
          mine ? "bg-rally-cobalt-50" : "border border-rally-line bg-white"
        }`}
        data-mine={mine || undefined}
      >
        {/* Meta read first by a screen reader ("You, 8:02 AM"), shown after. */}
        <span className="sr-only">{`${who}, ${time}: `}</span>
        <p className="whitespace-pre-wrap text-sm text-rally-ink">{message.body}</p>
        <p aria-hidden="true" className="mt-1 text-[11px] text-rally-subtle">
          {who} · {time}
          {mine && " ✓"}
        </p>
      </div>
    </li>
  );
}
