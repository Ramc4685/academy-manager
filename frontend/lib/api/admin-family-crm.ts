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
