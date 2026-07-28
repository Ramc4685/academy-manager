/**
 * v2 session-type billing client.
 *
 * Session types are the pricing catalog (monthly vs per-session, price,
 * overage rate) behind billing enrollments.
 * Backed by `backend/v2/interfaces/admin/session_type_routes.py`.
 */
import { apiFetch } from "../client";

export type SessionTypeBillingPeriod = "monthly" | "per_session";

export interface SessionTypeView {
  session_type_id: string;
  name: string;
  description: string | null;
  price_cents: number;
  billing_period: SessionTypeBillingPeriod;
  overage_rate_cents: number | null;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface SessionTypeList {
  session_types: SessionTypeView[];
}

export interface CreateSessionTypeRequest {
  name: string;
  description?: string | null;
  price_cents: number;
  billing_period?: SessionTypeBillingPeriod;
  overage_rate_cents?: number | null;
}

export interface UpdateSessionTypeRequest {
  name?: string;
  description?: string | null;
  price_cents?: number;
  billing_period?: SessionTypeBillingPeriod;
  overage_rate_cents?: number | null;
  is_active?: boolean;
}

/**
 * Archived (soft-deleted) types are excluded unless `includeArchived` is set —
 * the backend defaults `include_archived` to false.
 */
export function listSessionTypes(
  options: { includeArchived?: boolean } = {},
): Promise<SessionTypeList> {
  const path = options.includeArchived
    ? "/admin/session-types?include_archived=true"
    : "/admin/session-types";
  return apiFetch<SessionTypeList>(path);
}

export function createSessionType(
  payload: CreateSessionTypeRequest,
): Promise<SessionTypeView> {
  return apiFetch<SessionTypeView>("/admin/session-types", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function updateSessionType(
  sessionTypeId: string,
  payload: UpdateSessionTypeRequest,
): Promise<SessionTypeView> {
  return apiFetch<SessionTypeView>(
    `/admin/session-types/${encodeURIComponent(sessionTypeId)}`,
    {
      method: "PATCH",
      body: JSON.stringify(payload),
    },
  );
}

export function archiveSessionType(sessionTypeId: string): Promise<void> {
  return apiFetch<void>(`/admin/session-types/${encodeURIComponent(sessionTypeId)}`, {
    method: "DELETE",
  });
}
