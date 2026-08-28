/**
 * Platform-operator API client.
 *
 * Backed by backend/v2/interfaces/platform/*. Every route here 404s (not 403)
 * for non-platform callers, so a failed request is indistinguishable from a
 * missing route by design — surface it as "unavailable", not "forbidden".
 */

import { apiFetch } from "./client";

export type TenantStatus = "provisioning" | "active" | "suspended" | "cancelled";

export interface TenantLimits {
  max_students: number | null;
  max_coaches: number | null;
  max_locations: number | null;
}

export interface PlatformTenant {
  academy_id: string;
  display_name: string;
  slug: string;
  primary_domain: string;
  status: TenantStatus;
  servable: boolean;
  reason: string | null;
  plan_code: string;
  limits: TenantLimits;
  status_reason: string | null;
  updated_by: string;
}

export interface TenantHealth {
  academy_id: string;
  status: TenantStatus;
  servable: boolean;
  reason: string | null;
  plan_code: string;
  limits: TenantLimits;
}

export interface CreateTenantPayload {
  display_name: string;
  slug: string;
  primary_domain: string;
  plan_code: string;
  limits: Partial<TenantLimits>;
}

export interface UpdateTenantPlanPayload {
  plan_code: string;
  limits: Partial<TenantLimits>;
}

export function listPlatformTenants(): Promise<PlatformTenant[]> {
  return apiFetch<PlatformTenant[]>("/platform/tenants", { method: "GET" });
}

export function getPlatformTenantStatus(academyId: string): Promise<PlatformTenant> {
  return apiFetch<PlatformTenant>(
    `/platform/tenants/${encodeURIComponent(academyId)}/status`,
    { method: "GET" },
  );
}

export function getPlatformTenantHealth(academyId: string): Promise<TenantHealth> {
  return apiFetch<TenantHealth>(
    `/platform/tenants/${encodeURIComponent(academyId)}/health`,
    { method: "GET" },
  );
}

export function createPlatformTenant(payload: CreateTenantPayload): Promise<PlatformTenant> {
  return apiFetch<PlatformTenant>("/platform/tenants", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function activatePlatformTenant(academyId: string): Promise<PlatformTenant> {
  return apiFetch<PlatformTenant>(
    `/platform/tenants/${encodeURIComponent(academyId)}/activate`,
    { method: "POST" },
  );
}

export function reactivatePlatformTenant(academyId: string): Promise<PlatformTenant> {
  return apiFetch<PlatformTenant>(
    `/platform/tenants/${encodeURIComponent(academyId)}/reactivate`,
    { method: "POST" },
  );
}

export function suspendPlatformTenant(
  academyId: string,
  payload: { reason: string },
): Promise<PlatformTenant> {
  return apiFetch<PlatformTenant>(
    `/platform/tenants/${encodeURIComponent(academyId)}/suspend`,
    { method: "POST", body: JSON.stringify(payload) },
  );
}

export function cancelPlatformTenant(
  academyId: string,
  payload: { reason: string },
): Promise<PlatformTenant> {
  return apiFetch<PlatformTenant>(
    `/platform/tenants/${encodeURIComponent(academyId)}/cancel`,
    { method: "POST", body: JSON.stringify(payload) },
  );
}

export function updatePlatformTenantPlan(
  academyId: string,
  payload: UpdateTenantPlanPayload,
): Promise<PlatformTenant> {
  return apiFetch<PlatformTenant>(
    `/platform/tenants/${encodeURIComponent(academyId)}/plan`,
    { method: "PATCH", body: JSON.stringify(payload) },
  );
}

export interface BootstrapAcademyPayload {
  display_name: string;
  slug: string;
  primary_domain: string;
  owner_email: string;
  owner_display_name: string;
  timezone: string;
}

export interface BootstrapAcademyResult {
  academy_id: string;
  slug: string;
  primary_domain: string;
  owner_user_id: string;
  membership_id: string;
  owner_role: string;
  created: boolean;
  default_records: string[];
}

export function bootstrapPlatformAcademy(
  payload: BootstrapAcademyPayload,
): Promise<BootstrapAcademyResult> {
  return apiFetch<BootstrapAcademyResult>("/platform/academies/bootstrap", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}
