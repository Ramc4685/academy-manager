/**
 * v2 memberships client.
 *
 * Returns the academies the current user has an active membership in,
 * used by the tenant/academy switcher. Backed by the identity domain
 * (`academy_memberships` collection, `list_memberships_for_user` repo
 * method) via `GET /me/memberships`.
 */
import { apiFetch } from "../client";

export type MembershipRole = "admin" | "coach" | "parent" | "owner";

export interface AcademyMembershipSummary {
  academy_id: string;
  academy_name: string;
  academy_slug: string | null;
  roles: MembershipRole[];
  status: "active" | "suspended" | "removed";
  is_default: boolean;
}

export interface MyMembershipsResponse {
  memberships: AcademyMembershipSummary[];
  active_academy_id: string;
}

interface RawMembershipSummary {
  academy_id: string;
  academy_name: string | null;
  academy_slug: string | null;
  roles: MembershipRole[];
  status: "active" | "suspended" | "removed";
  is_default: boolean;
}

interface RawMyMembershipsResponse {
  memberships: RawMembershipSummary[];
  active_academy_id: string;
}

/**
 * Fetch the current user's academy memberships.
 */
export async function listMyMemberships(): Promise<MyMembershipsResponse> {
  const raw = await apiFetch<RawMyMembershipsResponse>("/me/memberships");
  return {
    active_academy_id: raw.active_academy_id,
    memberships: raw.memberships.map((m) => ({
      ...m,
      academy_name: m.academy_name || deriveAcademyLabel(m.academy_id),
    })),
  };
}

function deriveAcademyLabel(academyId: string): string {
  // The id surface is opaque; show a friendly placeholder until the
  // BFF returns display names. Truncate long ids so the switcher pill
  // remains readable.
  const trimmed = academyId.replace(/^academy[-_]/i, "").trim();
  if (!trimmed) return "Active academy";
  if (trimmed.length <= 18) return trimmed;
  return `${trimmed.slice(0, 8)}…${trimmed.slice(-4)}`;
}
