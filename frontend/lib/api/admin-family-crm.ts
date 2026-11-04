/**
 * People CRM Phase 4a: team notes and follow-ups on a family record.
 * Shapes mirror backend/v2/interfaces/admin/family_crm_routes.py.
 *
 * - `GET/POST /admin/families/{parentId}/notes`
 * - `PATCH/DELETE /admin/families/{parentId}/notes/{noteId}` (author or owner)
 * - `GET/POST /admin/families/{parentId}/follow-ups`
 * - `PATCH /admin/families/{parentId}/follow-ups/{followUpId}`
 * - `GET /admin/follow-ups?assignee=me|all&bucket=overdue|today|upcoming|done`
 */
import { apiFetch } from "./client";

export interface FamilyNote {
  note_id: string;
  parent_id: string;
  /** Plain text with line breaks; never HTML. */
  body: string;
  author_user_id: string;
  created_at: string;
  updated_at: string;
  edited: boolean;
  /** True for the author and for academy owners. */
  can_edit: boolean;
}

export interface FamilyNoteList {
  family_id: string;
  notes: FamilyNote[];
}

export type FollowUpStatus = "open" | "done";
export type FollowUpBucket = "overdue" | "today" | "upcoming" | "done";

export interface FollowUp {
  follow_up_id: string;
  parent_id: string;
  family_name: string | null;
  title: string;
  /** ISO date (YYYY-MM-DD). */
  due_on: string;
  assignee_user_id: string;
  status: FollowUpStatus;
  bucket: FollowUpBucket;
  created_by: string;
  created_at: string;
  updated_at: string;
  done_at: string | null;
  done_by: string | null;
}

export interface FamilyFollowUpList {
  family_id: string;
  /** The academy's local date. */
  today: string;
  follow_ups: FollowUp[];
}

export interface FollowUpQueue {
  today: string;
  assignee: "me" | "all";
  bucket: FollowUpBucket | null;
  follow_ups: FollowUp[];
}

export interface NewFollowUp {
  title: string;
  due_on: string;
  assignee_user_id: string;
}

export type FollowUpPatch = Partial<NewFollowUp & { status: FollowUpStatus }>;

const family = (parentId: string) => `/admin/families/${encodeURIComponent(parentId)}`;

export function fetchFamilyNotes(parentId: string): Promise<FamilyNoteList> {
  return apiFetch<FamilyNoteList>(`${family(parentId)}/notes`, { method: "GET" });
}

export function addFamilyNote(parentId: string, body: string): Promise<FamilyNote> {
  return apiFetch<FamilyNote>(`${family(parentId)}/notes`, {
    method: "POST",
    body: JSON.stringify({ body }),
  });
}

export function editFamilyNote(parentId: string, noteId: string, body: string): Promise<FamilyNote> {
  return apiFetch<FamilyNote>(`${family(parentId)}/notes/${encodeURIComponent(noteId)}`, {
    method: "PATCH",
    body: JSON.stringify({ body }),
  });
}

export function deleteFamilyNote(parentId: string, noteId: string): Promise<void> {
  return apiFetch<void>(`${family(parentId)}/notes/${encodeURIComponent(noteId)}`, {
    method: "DELETE",
  });
}

export function fetchFamilyFollowUps(parentId: string): Promise<FamilyFollowUpList> {
  return apiFetch<FamilyFollowUpList>(`${family(parentId)}/follow-ups`, { method: "GET" });
}

export function addFamilyFollowUp(parentId: string, payload: NewFollowUp): Promise<FollowUp> {
  return apiFetch<FollowUp>(`${family(parentId)}/follow-ups`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function updateFamilyFollowUp(
  parentId: string,
  followUpId: string,
  patch: FollowUpPatch,
): Promise<FollowUp> {
  return apiFetch<FollowUp>(
    `${family(parentId)}/follow-ups/${encodeURIComponent(followUpId)}`,
    { method: "PATCH", body: JSON.stringify(patch) },
  );
}

export function fetchFollowUpQueue(
  assignee: "me" | "all",
  bucket?: FollowUpBucket,
): Promise<FollowUpQueue> {
  const params = new URLSearchParams({ assignee });
  if (bucket) params.set("bucket", bucket);
  return apiFetch<FollowUpQueue>(`/admin/follow-ups?${params.toString()}`, { method: "GET" });
}

// ---------------------------------------------------------------------------
// People CRM Phase 6 (L4c): the family Messages tab. The app sends no SMS or
// WhatsApp; staff hand off to their own app and log the contact here.
// ---------------------------------------------------------------------------

export type MessageChannel = "email" | "whatsapp" | "sms" | "call" | "in_person";
export type MessageSource = "campaign" | "digest" | "absence_notice" | "invoice_copy" | "staff_log";
export type MessageStatus = "queued" | "sent" | "opened" | "failed" | "logged" | "not_logged";

export interface FamilyMessage {
  entry_id: string;
  at: string;
  channel: MessageChannel;
  source: MessageSource;
  status: MessageStatus;
  summary: string;
  detail: string | null;
  recipient: string | null;
  author_user_id: string | null;
  failed_reason: string | null;
  log_id: string | null;
  /** A `not_logged` handoff the caller may still confirm as sent. */
  can_complete: boolean;
}

export interface FamilyMessageList {
  family_id: string;
  entries: FamilyMessage[];
  warnings: string[];
}

export interface NewContactLog {
  channel: MessageChannel;
  status: "logged" | "not_logged";
  note?: string | null;
}

export function fetchFamilyMessages(parentId: string): Promise<FamilyMessageList> {
  return apiFetch<FamilyMessageList>(`${family(parentId)}/messages`, { method: "GET" });
}

export function logFamilyContact(parentId: string, payload: NewContactLog): Promise<FamilyMessage> {
  return apiFetch<FamilyMessage>(`${family(parentId)}/messages/log`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function completeFamilyContactLog(
  parentId: string,
  logId: string,
  note: string | null = null,
): Promise<FamilyMessage> {
  return apiFetch<FamilyMessage>(`${family(parentId)}/messages/log/${encodeURIComponent(logId)}`, {
    method: "PATCH",
    body: JSON.stringify({ status: "logged", note }),
  });
}
