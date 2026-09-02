/**
 * v2 coach/parent messages inbox client (UIM13).
 *
 * Thin read + mark-read surface over the shared comms store. Admin already
 * has its own send UI (`lib/api/admin.ts`); this module is the read-only
 * counterpart for the coach and parent personas.
 */
import { apiFetch } from "../client";

export type MessageKind = "dm" | "announcement";
export type MessageSenderPersona = "admin" | "coach" | "parent";

export interface InboxMessage {
  message_id: string;
  kind: MessageKind;
  sender_persona: MessageSenderPersona;
  body: string;
  created_at: string;
  read: boolean;
  /**
   * Session title for a session-scoped announcement (#614). A family with
   * three children in three classes cannot tell which class an announcement
   * is about without it. Null for DMs and academy-wide announcements.
   */
  scope_label?: string | null;
  urgency?: "routine" | "urgent";
  author_display_name?: string | null;
}

export interface InboxMessagesResponse {
  messages: InboxMessage[];
}

export interface MarkMessageReadResponse {
  status: "ok";
}

export function listCoachMessages(): Promise<InboxMessagesResponse> {
  return apiFetch<InboxMessagesResponse>("/coach/messages", { method: "GET" });
}

export function markCoachMessageRead(messageId: string): Promise<MarkMessageReadResponse> {
  return apiFetch<MarkMessageReadResponse>(
    `/coach/messages/${encodeURIComponent(messageId)}/read`,
    { method: "POST" },
  );
}

export function listParentMessages(): Promise<InboxMessagesResponse> {
  return apiFetch<InboxMessagesResponse>("/parent/messages", { method: "GET" });
}

export function markParentMessageRead(messageId: string): Promise<MarkMessageReadResponse> {
  return apiFetch<MarkMessageReadResponse>(
    `/parent/messages/${encodeURIComponent(messageId)}/read`,
    { method: "POST" },
  );
}
