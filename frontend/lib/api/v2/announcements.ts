/**
 * Session announcements (#614) — admin and coach authoring surface.
 *
 * Both personas post to the same shared comms store through their own BFF
 * prefix, so the two callers differ only in that prefix. Parents never author;
 * they read announcements through the messages inbox.
 */
import { apiFetch } from "../client";

export type AnnouncementUrgency = "routine" | "urgent";

/** `failed` still means the announcement was posted — only the email failed. */
export type AnnouncementEmailStatus =
  | "skipped"
  | "sent"
  | "no_recipients"
  | "failed";

export interface SessionAnnouncement {
  message_id: string;
  session_id: string;
  body: string;
  urgency: AnnouncementUrgency;
  author_id: string;
  author_display_name: string | null;
  author_persona: "admin" | "coach" | "parent";
  created_at: string;
  /**
   * Whether the CURRENT viewer may delete it, decided server-side (admin may
   * delete any; a coach only their own). The client renders the affordance
   * from this flag rather than re-deriving an authorization rule.
   */
  can_delete: boolean;
}

export interface SessionAnnouncementList {
  announcements: SessionAnnouncement[];
}

export interface PostSessionAnnouncementRequest {
  body: string;
  urgent: boolean;
}

export interface PostSessionAnnouncementResponse {
  announcement: SessionAnnouncement;
  email_status: AnnouncementEmailStatus;
  sent_count: number;
  failed_count: number;
}

export type AnnouncementPersona = "admin" | "coach";

function base(persona: AnnouncementPersona, sessionId: string): string {
  return `/${persona}/sessions/${encodeURIComponent(sessionId)}/announcements`;
}

export function listSessionAnnouncements(
  persona: AnnouncementPersona,
  sessionId: string,
): Promise<SessionAnnouncementList> {
  return apiFetch<SessionAnnouncementList>(base(persona, sessionId), {
    method: "GET",
  });
}

export function postSessionAnnouncement(
  persona: AnnouncementPersona,
  sessionId: string,
  body: PostSessionAnnouncementRequest,
): Promise<PostSessionAnnouncementResponse> {
  return apiFetch<PostSessionAnnouncementResponse>(base(persona, sessionId), {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function deleteSessionAnnouncement(
  persona: AnnouncementPersona,
  sessionId: string,
  messageId: string,
): Promise<void> {
  return apiFetch<void>(
    `${base(persona, sessionId)}/${encodeURIComponent(messageId)}`,
    { method: "DELETE" },
  );
}
