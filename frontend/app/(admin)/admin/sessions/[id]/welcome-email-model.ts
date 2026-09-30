/**
 * The Welcome email tab's data rules, kept free of React so they can be unit
 * tested: which of a class's seven onboarding facts is its own value, which
 * falls back to the academy default, and what a Save is allowed to send.
 */

import type { AdminAcademyView, AdminSessionView, EditSessionRequest } from "@/lib/api/admin";

import { blankToNull } from "./format";

export type PackField =
  | "whatsapp_group_link"
  | "venue_address"
  | "parking_notes"
  | "what_to_bring"
  | "arrival_minutes_before"
  | "coach_contact_policy"
  | "absence_policy";

export interface PackRowSpec {
  field: PackField;
  label: string;
  kind: "url" | "text" | "multiline" | "minutes";
  /** The WhatsApp link has no academy default: it is per class only. */
  hasDefault: boolean;
}

export const PACK_ROWS: readonly PackRowSpec[] = [
  { field: "whatsapp_group_link", label: "Group chat (WhatsApp) link", kind: "url", hasDefault: false },
  { field: "venue_address", label: "Venue address", kind: "multiline", hasDefault: true },
  { field: "parking_notes", label: "Parking notes", kind: "multiline", hasDefault: true },
  { field: "what_to_bring", label: "What to bring", kind: "multiline", hasDefault: true },
  { field: "arrival_minutes_before", label: "Arrive early", kind: "minutes", hasDefault: true },
  { field: "coach_contact_policy", label: "Coach contact", kind: "multiline", hasDefault: true },
  { field: "absence_policy", label: "Absences & make-ups", kind: "multiline", hasDefault: true },
];

/** The academy-side values the fallbacks come from, as plain strings. */
export type PackDefaults = Partial<Record<PackField, string>>;

/** Class defaults (Settings › Academy profile) plus the Family policies absence text. */
export function packDefaults(
  academy: AdminAcademyView | undefined,
  absencePolicyDefault: string | undefined,
): PackDefaults {
  return {
    venue_address: academy?.default_venue_address ?? "",
    parking_notes: academy?.default_parking_note ?? "",
    what_to_bring: academy?.default_what_to_bring ?? "",
    arrival_minutes_before: minutesText(academy?.default_arrival_minutes_before),
    coach_contact_policy: academy?.default_coach_contact_policy ?? "",
    absence_policy: absencePolicyDefault ?? "",
  };
}

/** 0 and null both mean "no arrival time": never shown as "0 minutes". */
function minutesText(value: number | null | undefined): string {
  return value != null && value > 0 ? String(value) : "";
}

/** A class's stored value as the string the tab edits. */
export function storedText(session: AdminSessionView, field: PackField): string {
  if (field === "arrival_minutes_before") return minutesText(session.arrival_minutes_before);
  return (session[field] ?? "").trim();
}

export type RowState =
  /** The class has its own value. */
  | { kind: "own"; text: string }
  /** Blank on the class; the academy default applies. */
  | { kind: "default"; text: string }
  | { kind: "unset" };

export function resolveRow(spec: PackRowSpec, own: string, defaults: PackDefaults): RowState {
  const ownText = own.trim();
  if (ownText !== "") return { kind: "own", text: ownText };
  const fallback = spec.hasDefault ? (defaults[spec.field] ?? "").trim() : "";
  if (fallback !== "") return { kind: "default", text: fallback };
  return { kind: "unset" };
}

export function displayText(spec: PackRowSpec, text: string): string {
  if (spec.kind !== "minutes") return text;
  const minutes = Number(text);
  return `${minutes} minute${minutes === 1 ? "" : "s"} before start`;
}

/**
 * The PATCH body for Save: only the pack fields whose draft differs from what
 * is stored, and nothing else — never the schedule, coach, seats or price. A
 * cleared field is an explicit `null`, which the server treats as "clear".
 */
export function buildPackPatch(
  session: AdminSessionView,
  drafts: Partial<Record<PackField, string>>,
): EditSessionRequest {
  const patch: Record<string, string | number | null> = {};
  for (const spec of PACK_ROWS) {
    const draft = drafts[spec.field];
    if (draft === undefined) continue;
    if (draft.trim() === storedText(session, spec.field)) continue;
    if (spec.kind === "minutes") {
      const minutes = Number.parseInt(draft.trim(), 10);
      patch[spec.field] = Number.isFinite(minutes) ? minutes : null;
    } else {
      patch[spec.field] = blankToNull(draft);
    }
  }
  return patch as EditSessionRequest;
}
