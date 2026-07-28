/**
 * v2 owner (franchise) client.
 *
 * `GET /owner/rollup` aggregates revenue and outstanding dues across every
 * academy the caller holds an active `owner` membership in. Scope is derived
 * server-side from those memberships — the active-academy header does not
 * affect what comes back. The route 404s when the caller owns no academies
 * or when the `enable_owner_role` flag is off.
 */
import { apiFetch } from "../client";

export interface OwnerAcademyRollupRow {
  academy_id: string;
  academy_name: string | null;
  revenue_by_month: Record<string, number>;
  collected_cents: number;
  outstanding_cents: number;
  outstanding_invoice_count: number;
}

export interface OwnerRollupTotals {
  academy_count: number;
  revenue_by_month: Record<string, number>;
  collected_cents: number;
  outstanding_cents: number;
  outstanding_invoice_count: number;
}

export interface OwnerRollup {
  academies: OwnerAcademyRollupRow[];
  totals: OwnerRollupTotals;
}

export async function getOwnerRollup(months?: string[]): Promise<OwnerRollup> {
  const query = months?.length
    ? `?${months.map((m) => `months=${encodeURIComponent(m)}`).join("&")}`
    : "";
  return apiFetch<OwnerRollup>(`/owner/rollup${query}`, { method: "GET" });
}
