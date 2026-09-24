/**
 * People CRM Phase 4c: the duplicate warning on Add parent / Add user / Add
 * contact. Mirrors backend/v2/interfaces/admin/people_duplicate_routes.py:
 *
 * - `POST /admin/people/duplicate-check` `{email?, phone?, name?}` ->
 *   `{matches: DuplicateMatch[]}` (at most five, contact details masked).
 *
 * A warning only: callers show it and let staff continue. No request
 * carries an academy: the backend uses the caller's tenant.
 */
import { apiFetch } from "./client";

export type DuplicateKind = "family" | "family_contact" | "user" | "inquiry";

export interface DuplicateMatch {
  kind: DuplicateKind;
  display_name: string;
  email_masked: string | null;
  phone_masked: string | null;
  /** The admin page that opens the record; null for an unlinked inquiry. */
  link: string | null;
  matched_on: Array<"email" | "phone" | "name">;
}

export interface DuplicateCheckResponse {
  matches: DuplicateMatch[];
}

export interface DuplicateProbe {
  email: string | null;
  phone: string | null;
  name: string | null;
}

const MIN_PHONE_DIGITS = 7;

/**
 * What is worth asking about, or null when nothing is. The backend applies
 * the same rules; this only saves a round trip for a half-typed field.
 */
export function duplicateProbe(fields: {
  email?: string | null;
  phone?: string | null;
  name?: string | null;
}): DuplicateProbe | null {
  const email = (fields.email ?? "").trim().toLowerCase();
  const phone = (fields.phone ?? "").trim();
  const name = (fields.name ?? "").trim().replace(/\s+/g, " ");
  const probe: DuplicateProbe = {
    email: /^[^@\s]+@[^@\s]+$/.test(email) ? email : null,
    phone: phone.replace(/\D/g, "").length >= MIN_PHONE_DIGITS ? phone : null,
    name: name || null,
  };
  // The check runs when an email or phone field is left, so a name alone
  // (typed first, before either) is not worth a request yet.
  if (probe.email === null && probe.phone === null) return null;
  return probe;
}

export function sameProbe(a: DuplicateProbe | null, b: DuplicateProbe | null): boolean {
  if (a === null || b === null) return a === b;
  return a.email === b.email && a.phone === b.phone && a.name === b.name;
}

export function checkPossibleDuplicates(probe: DuplicateProbe): Promise<DuplicateCheckResponse> {
  return apiFetch<DuplicateCheckResponse>("/admin/people/duplicate-check", {
    method: "POST",
    body: JSON.stringify(probe),
  });
}

const KIND_LABELS: Record<DuplicateKind, string> = {
  family: "family",
  family_contact: "family contact",
  user: "user",
  inquiry: "inquiry",
};

export function duplicateKindLabel(kind: DuplicateKind): string {
  return KIND_LABELS[kind];
}
