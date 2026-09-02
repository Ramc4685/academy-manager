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

export type SupervisableRole = "admin" | "coach" | "parent" | "student" | "owner";

export const COACH_SUPERVISOR_ROLES: readonly SupervisableRole[] = ["admin", "owner"];

/** Roles that render as a persona shell with a home route. */
const PERSONA_VIEW_ORDER: readonly SupervisableRole[] = ["admin", "coach", "parent", "student"];

export function canSuperviseCoaching(roles: readonly SupervisableRole[]): boolean {
  return COACH_SUPERVISOR_ROLES.some((role) => roles.includes(role));
}

/**
 * Persona views the user can switch to: every persona role they hold, plus
 * the coach view when they can supervise coaching. Ordered admin → coach →
 * parent → student like the switcher. `owner` is a scope, not a view.
 */
export function availablePersonaViews(
  roles: readonly SupervisableRole[],
): Array<Exclude<SupervisableRole, "owner">> {
  const withCoach = canSuperviseCoaching(roles) ? [...roles, "coach" as const] : roles;
  return PERSONA_VIEW_ORDER.filter(
    (view): view is Exclude<SupervisableRole, "owner"> => withCoach.includes(view),
  );
}
