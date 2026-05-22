/**
 * v2 memberships client.
 *
 * Returns the academies the current user has an active membership in,
 * used by the tenant/academy switcher. Backed by Wave 1 identity domain
 * (`academy_memberships` collection, `list_memberships_for_user` repo
 * method).
 *
 * NOTE: As of the Wave 5 cut, no BFF route exposes `/me/memberships`
 * yet — the `/me` endpoint only returns a single resolved academy.
 * Until that endpoint lands, this client falls back to a single-academy
 * stub derived from `getCurrentUser()`. Replace `listMyMemberships()`
 * with a real `apiFetch` once the route exists; the call sites and the
 * `TenantContext` already deal with the multi-academy shape.
 */
import { apiFetch } from "../client";
import { getCurrentUser } from "../me";

export type MembershipRole = "admin" | "coach" | "parent";

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

/**
 * Fetch the current user's academy memberships.
 *
 * TODO(wave5-A): switch to the real `/me/memberships` BFF endpoint
 * once it ships. Current behaviour returns a single-academy summary
 * by reading `/me` so the switcher renders meaningfully today.
 */
export async function listMyMemberships(): Promise<MyMembershipsResponse> {
  try {
    const real = await apiFetch<MyMembershipsResponse>("/me/memberships", {
      method: "GET",
    });
    if (real && Array.isArray(real.memberships) && real.memberships.length > 0) {
      return real;
    }
  } catch (err) {
    // Endpoint may not exist yet; fall back to the single-academy stub
    // derived from `/me`. Log only in dev to make the fallback obvious.
    if (process.env.NODE_ENV === "development") {
      // eslint-disable-next-line no-console
      console.debug("[memberships] /me/memberships unavailable, using fallback", err);
    }
  }

  const me = await getCurrentUser();
  return {
    memberships: [
      {
        academy_id: me.academy_id,
        academy_name: deriveAcademyLabel(me.academy_id),
        academy_slug: null,
        roles: me.roles as MembershipRole[],
        status: "active",
        is_default: true,
      },
    ],
    active_academy_id: me.academy_id,
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
