/**
 * Coach supervision (#632).
 *
 * The coach shell is a *surface*, not a role: an academy admin or owner may
 * open it to cover any session — see every class on Today / Sessions and
 * mark attendance for any of them. Mirrors `COACH_SUPERVISOR_ROLES` in
 * `backend/v2/shared/http/persona.py`; keep the two lists in sync.
 *
 * Pure helpers with no imports so `coach-supervisor.node-test.mjs` can load
 * them under plain Node.
 */

export type SupervisableRole =
  | "admin"
  | "coach"
  | "assistant_coach"
  | "parent"
  | "student"
  | "owner";

export const COACH_SUPERVISOR_ROLES: readonly SupervisableRole[] = ["admin", "owner"];

/**
 * Every role admitted to the coach shell: coaches, per-session assistant
 * coaches, and the supervisors above. Mirrors `require_coach_surface()` in
 * `backend/v2/shared/http/persona.py`.
 */
export const COACH_SURFACE_ROLES: readonly SupervisableRole[] = [
  "coach",
  "assistant_coach",
  ...COACH_SUPERVISOR_ROLES,
];

/** Roles that render as a persona shell with a home route. */
const PERSONA_VIEW_ORDER: readonly SupervisableRole[] = ["admin", "coach", "parent", "student"];

export function canSuperviseCoaching(roles: readonly SupervisableRole[]): boolean {
  return COACH_SUPERVISOR_ROLES.some((role) => roles.includes(role));
}

/**
 * Assistant coach *only*: sees the coach shell scoped to the sessions that
 * list them and may mark attendance, update skills and write notes there —
 * never lesson plans, rosters, billing or family messaging. Anyone who also
 * holds coach/admin/owner keeps the full surface, so this is false for them.
 */
export function isAssistantCoach(roles: readonly SupervisableRole[]): boolean {
  if (!roles.includes("assistant_coach")) return false;
  return !roles.includes("coach") && !canSuperviseCoaching(roles);
}

/**
 * Academy owner: the money-governance scope (refunds, pricing, payouts,
 * reports, audit, admin/owner role grants). Mirrors `require_owner()` in
 * `backend/v2/shared/http/persona.py`. `owner` is a scope layered on top of
 * the admin persona, never a view of its own.
 */
export function isOwner(roles: readonly SupervisableRole[]): boolean {
  return roles.includes("owner");
}

/**
 * Persona views the user can switch to: every persona role they hold, plus
 * the coach view when they can supervise coaching or assist on sessions.
 * Ordered admin → coach → parent → student like the switcher. `owner` is a
 * scope, not a view; `assistant_coach` maps onto the coach view.
 */
export function availablePersonaViews(
  roles: readonly SupervisableRole[],
): Array<Exclude<SupervisableRole, "owner" | "assistant_coach">> {
  const withCoach =
    canSuperviseCoaching(roles) || roles.includes("assistant_coach")
      ? [...roles, "coach" as const]
      : roles;
  return PERSONA_VIEW_ORDER.filter(
    (view): view is Exclude<SupervisableRole, "owner" | "assistant_coach"> =>
      withCoach.includes(view),
  );
}
