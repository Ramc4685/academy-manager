"use client";

/**
 * Session announcements composer + history (#614).
 *
 * Shared by the admin session detail page and the coach session detail page:
 * the two surfaces post to the same store through their own BFF prefix and
 * differ only in that prefix and in who may delete what, so the composer,
 * the confirm copy and the sent/failed reporting exist once here rather than
 * drifting between two near-identical files. Each page supplies its own
 * chrome (admin wraps this in a Card + LaneHeader, coach in a plain section).
 *
 * Bodies are rendered as React text children with `whitespace-pre-wrap` — no
 * `dangerouslySetInnerHTML`, no markdown renderer. The email path escapes
 * separately in composition/session_announcements.py.
 */

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  deleteSessionAnnouncement,
  listSessionAnnouncements,
  postSessionAnnouncement,
  type AnnouncementEmailStatus,
  type AnnouncementPersona,
  type SessionAnnouncement,
} from "@/lib/api/v2/announcements";
import { queryKeys } from "@/lib/query/keys";

import { Button } from "@/components/ds/button";

const MAX_BODY = 2000;

const NO_EDIT_HELP =
  "Announcements can't be edited. Delete and repost instead — an email that has already gone out can't be recalled.";

const DELETE_CONFIRM =
  "Delete this announcement? It disappears from every family's inbox, but an email that has already gone out can't be recalled.";

function emailSummary(
  status: AnnouncementEmailStatus,
  sent: number,
  failed: number,
): string {
  switch (status) {
    case "sent":
      return failed > 0
        ? `Posted. Emailed ${sent} of ${sent + failed} families — ${failed} could not be reached.`
        : `Posted and emailed ${sent} ${sent === 1 ? "family" : "families"}.`;
    case "no_recipients":
      return "Posted. Nobody is enrolled in this session yet, so no email was sent.";
    case "failed":
      return "Posted, but the email could not be sent. Delete and repost to try again.";
    default:
      return "Posted to the portal inbox.";
  }
}

export function AnnouncementsPanel({
  persona,
  sessionId,
}: {
  persona: AnnouncementPersona;
  sessionId: string;
}) {
  const queryClient = useQueryClient();
  const queryKey =
    persona === "admin"
      ? queryKeys.admin.sessionAnnouncements(sessionId)
      : queryKeys.coach.sessionAnnouncements(sessionId);

  const [body, setBody] = useState("");
  const [urgent, setUrgent] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const announcementsQuery = useQuery({
    queryKey,
    queryFn: () => listSessionAnnouncements(persona, sessionId),
  });

  const invalidate = () =>
    void queryClient.invalidateQueries({ queryKey });

  const postMutation = useMutation({
    mutationFn: () =>
      postSessionAnnouncement(persona, sessionId, {
        body: body.trim(),
        urgent,
      }),
    onSuccess: (res) => {
      setBody("");
      setUrgent(false);
      setError(null);
      setNotice(
        emailSummary(res.email_status, res.sent_count, res.failed_count),
      );
      invalidate();
    },
    onError: () => {
      setNotice(null);
      setError("Could not post the announcement. Try again.");
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (messageId: string) =>
      deleteSessionAnnouncement(persona, sessionId, messageId),
    onSuccess: () => {
      setError(null);
      invalidate();
    },
    onError: () => setError("Could not delete the announcement."),
  });

  const announcements = announcementsQuery.data?.announcements ?? [];
  const trimmed = body.trim();
  const canPost = trimmed.length > 0 && !postMutation.isPending;

  return (
    <div data-testid="announcements-panel" className="space-y-4">
      <div className="space-y-2">
        <label htmlFor="announcement-body" className="sr-only">
          Announcement
        </label>
        <textarea
          id="announcement-body"
          data-testid="announcement-body"
          value={body}
          maxLength={MAX_BODY}
          rows={3}
          onChange={(e) => setBody(e.target.value)}
          placeholder="Tell this class something — a cancellation, a venue change, what to bring."
          className="w-full rounded-lg border border-rally-line p-3 text-sm text-rally-ink"
        />
        <label className="flex items-center gap-2 text-sm text-rally-ink">
          <input
            type="checkbox"
            data-testid="announcement-urgent"
            checked={urgent}
            onChange={(e) => setUrgent(e.target.checked)}
          />
          Urgent — email families now
        </label>
        <p className="text-xs text-rally-subtle">{NO_EDIT_HELP}</p>
        <div className="flex items-center gap-3">
          <Button
            variant="volt"
            size="sm"
            data-testid="announcement-post"
            disabled={!canPost}
            onClick={() => postMutation.mutate()}
          >
            {postMutation.isPending ? "Posting…" : "Post announcement"}
          </Button>
          <span className="font-mono text-[11px] tabular-nums text-rally-subtle">
            {trimmed.length}/{MAX_BODY}
          </span>
        </div>
        {notice && (
          <p
            data-testid="announcement-notice"
            className="text-sm text-rally-ink"
          >
            {notice}
          </p>
        )}
        {error && (
          <p role="alert" className="text-sm text-red-700">
            {error}
          </p>
        )}
      </div>

      {announcementsQuery.isLoading ? (
        <p className="text-sm text-rally-subtle">Loading announcements…</p>
      ) : announcements.length === 0 ? (
        <p
          className="text-sm text-rally-subtle"
          data-testid="announcements-empty"
        >
          No announcements yet.
        </p>
      ) : (
        <ul className="space-y-2" data-testid="announcement-history">
          {announcements.map((a) => (
            <AnnouncementRow
              key={a.message_id}
              announcement={a}
              canDelete={a.can_delete}
              deleting={
                deleteMutation.isPending &&
                deleteMutation.variables === a.message_id
              }
              onDelete={() => {
                if (confirm(DELETE_CONFIRM)) {
                  deleteMutation.mutate(a.message_id);
                }
              }}
            />
          ))}
        </ul>
      )}
    </div>
  );
}

function AnnouncementRow({
  announcement,
  canDelete,
  deleting,
  onDelete,
}: {
  announcement: SessionAnnouncement;
  canDelete: boolean;
  deleting: boolean;
  onDelete: () => void;
}) {
  return (
    <li
      data-testid={`announcement-${announcement.message_id}`}
      className="rounded-lg border border-rally-line p-3"
    >
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-xs font-semibold text-rally-ink">
              {announcement.author_display_name ?? "Staff"}
            </span>
            <span className="text-[11px] text-rally-subtle">
              {new Date(announcement.created_at).toLocaleString()}
            </span>
            {announcement.urgency === "urgent" && (
              <span
                data-testid="announcement-urgent-chip"
                className="rounded-full bg-status-red-50 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide text-status-red-800"
              >
                Urgent
              </span>
            )}
          </div>
          <p className="mt-1 whitespace-pre-wrap text-sm text-rally-ink">
            {announcement.body}
          </p>
        </div>
        {canDelete && (
          <Button
            variant="danger"
            size="sm"
            data-testid={`announcement-delete-${announcement.message_id}`}
            disabled={deleting}
            onClick={onDelete}
          >
            {deleting ? "Deleting…" : "Delete"}
          </Button>
        )}
      </div>
    </li>
  );
}
