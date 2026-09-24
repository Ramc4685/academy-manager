/**
 * People CRM Pipeline board (roadmap L3a moves, L3b board). Mirrors
 * backend/v2/interfaces/admin/pipeline_routes.py:
 *
 * - `GET /admin/crm/pipeline` -> every card on the board (crm_contacts leads
 *   plus trial and lead-only families from the family index).
 * - `POST /admin/crm/contacts` -> quick add lead (staff sources only).
 * - `POST /admin/crm/contacts/{id}/pipeline-move` `{to_column}` -> the card's
 *   new position; 409 `Crm.PipelineMoveNotAllowed` with `details.reason`.
 *
 * No money on a card. No request carries an academy.
 */
import { apiFetch } from "./client";

export const PIPELINE_COLUMNS = [
  "inquiry",
  "trial_booked",
  "trial_done",
  "registered",
  "enrolled",
] as const;
export type PipelineColumn = (typeof PIPELINE_COLUMNS)[number];

export const PIPELINE_COLUMN_LABELS: Record<PipelineColumn, string> = {
  inquiry: "Inquiry",
  trial_booked: "Trial booked",
  trial_done: "Trial done",
  registered: "Registered",
  enrolled: "Enrolled",
};

export type QuickAddSource = "whatsapp_or_phone" | "referral" | "other";

export const SOURCE_LABELS: Record<string, string> = {
  website: "Website",
  whatsapp_or_phone: "WhatsApp or phone",
  referral: "Referral",
  other: "Other",
};

export interface PipelineCard {
  card_id: string;
  kind: "contact" | "family";
  column: PipelineColumn;
  name: string;
  contact_id: string | null;
  family_id: string | null;
  child: string | null;
  child_age: string | null;
  source: string | null;
  created_at: string | null;
  lead_age_days: number | null;
  override_column: string | null;
  override_set_by: string | null;
  override_set_at: string | null;
  /** Columns a staff move may take this card to now; empty = read-only. */
  move_targets: PipelineColumn[];
}

export interface PipelineBoardResponse {
  generated_at: string;
  cards: PipelineCard[];
  warnings: string[];
}

export interface QuickAddLeadInput {
  name: string;
  phone?: string | null;
  email?: string | null;
  child_name?: string | null;
  child_age?: string | null;
  source: QuickAddSource;
}

export function isPipelineColumn(value: string | null | undefined): value is PipelineColumn {
  return !!value && (PIPELINE_COLUMNS as readonly string[]).includes(value);
}

export function fetchPipelineBoard(): Promise<PipelineBoardResponse> {
  return apiFetch<PipelineBoardResponse>("/admin/crm/pipeline", { method: "GET" });
}

export function quickAddLead(input: QuickAddLeadInput): Promise<PipelineCard> {
  return apiFetch<PipelineCard>("/admin/crm/contacts", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function movePipelineCard(
  contactId: string,
  toColumn: Exclude<PipelineColumn, "enrolled">,
): Promise<{ contact_id: string; column: PipelineColumn }> {
  return apiFetch(`/admin/crm/contacts/${encodeURIComponent(contactId)}/pipeline-move`, {
    method: "POST",
    body: JSON.stringify({ to_column: toColumn }),
  });
}

/** Cards grouped by column, in board order; each column keeps server order. */
export function groupByColumn(cards: PipelineCard[]): Record<PipelineColumn, PipelineCard[]> {
  const groups = Object.fromEntries(PIPELINE_COLUMNS.map((c) => [c, [] as PipelineCard[]])) as Record<
    PipelineColumn,
    PipelineCard[]
  >;
  for (const card of cards) {
    if (isPipelineColumn(card.column)) groups[card.column].push(card);
  }
  return groups;
}

/**
 * Where focus goes after `cardId` leaves `column` (WCAG 2.4.3): the card
 * that was after it, else the one before it, else null (the column heading).
 */
export function focusAfterLeaving(columnCards: PipelineCard[], cardId: string): string | null {
  const index = columnCards.findIndex((card) => card.card_id === cardId);
  if (index < 0) return null;
  const next = columnCards[index + 1] ?? columnCards[index - 1];
  return next ? next.card_id : null;
}
