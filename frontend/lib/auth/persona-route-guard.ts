/**
 * Server-side persona gate (#451).
 *
 * The persona shells only ever checked roles in the browser: every shell
 * waits for Firebase plus a `/me` round trip before deciding, so a
 * signed-out or wrong-persona visitor sees the shell flicker first and is
 * bounced afterwards. `middleware.ts` calls `decidePersonaRedirect` at the
 * edge to settle the obvious cases before anything paints.
 *
 * This is a **UX hint, not authorisation**. It reads a non-HttpOnly cookie
 * that the client writes after `/me` answers, so it can be stale or forged;
 * the backend's 404-on-wrong-persona is still the real gate, and the hint
 * never *grants* access — it can only redirect. Anything ambiguous fails
 * open and lets the client/backend decide.
 *
 * Pure helpers with no imports: `middleware.ts` runs on the Cloudflare
 * Workers edge runtime (OpenNext) where Node APIs do not exist, and
 * `persona-route-guard.node-test.mjs` loads this file under plain Node.
 */

export type PersonaHint =
  | "admin"
  | "coach"
  | "parent"
  | "student"
  | "owner"
  | "platform";

/** Written by the client once `/me` has answered; readable at the edge. */
export const PERSONA_HINT_COOKIE = "__cm_persona";

/** The BFF bridge cookie (`lib/api/auth-bridge-cookie.ts`). */
export const IDENTITY_COOKIE = "__cm_identity";

/**
 * Guarded prefixes. `/owner` and `/student` stay out: owner is a scope on
 * top of admin rather than a shell, and the student surface is reachable by
 * accounts that also hold `parent`.
 */
export const PERSONA_PATH_MATCHER: readonly string[] = [
  "/admin/:path*",
  "/coach/:path*",
  "/parent/:path*",
  "/platform/:path*",
];

const GUARDED_PREFIXES: readonly (readonly [string, PersonaHint])[] = [
  ["/admin", "admin"],
  ["/coach", "coach"],
  ["/parent", "parent"],
  ["/platform", "platform"],
];

/**
 * Landing route per persona, in the same priority order as `homeForRoles`
 * in `lib/api/me.ts` — keep the two in sync.
 */
const PERSONA_HOMES: readonly (readonly [PersonaHint, string])[] = [
  ["admin", "/admin"],
  ["coach", "/coach/today"],
  ["parent", "/parent/payments"],
  ["student", "/student/dashboard"],
  ["owner", "/owner"],
  ["platform", "/platform"],
];

const KNOWN_PERSONAS: readonly PersonaHint[] = PERSONA_HOMES.map(
  ([persona]) => persona,
);

export interface PersonaRouteRequest {
  pathname: string;
  /** Raw query string including the leading `?`, or "". */
  search?: string;
  /** Raw `__cm_persona` cookie value, if the browser sent one. */
  personaHint?: string;
  /** Whether the `__cm_identity` bridge cookie rode along. */
  hasIdentity?: boolean;
  /** `NEXT_PUBLIC_E2E_AUTH_BYPASS === "1"` — e2e runs without real cookies. */
  bypassAuth?: boolean;
}

/** The persona that owns `pathname`, or null when it is not guarded. */
export function personaForPath(pathname: string): PersonaHint | null {
  for (const [prefix, persona] of GUARDED_PREFIXES) {
    if (pathname === prefix || pathname.startsWith(`${prefix}/`)) {
      return persona;
    }
  }
  return null;
}

export function matchesPersonaPath(pathname: string): boolean {
  return personaForPath(pathname) !== null;
}

/** Known personas named by the cookie; unknown tokens are dropped. */
export function parsePersonaHint(raw: string | undefined): PersonaHint[] {
  if (!raw) return [];
  const seen: PersonaHint[] = [];
  for (const token of raw.split(",")) {
    const candidate = token.trim();
    for (const persona of KNOWN_PERSONAS) {
      if (candidate === persona && !seen.includes(persona)) seen.push(persona);
    }
  }
  return seen;
}

/** Cookie value for a user's roles: every persona they may enter. */
export function personaHintForRoles(
  roles: readonly string[],
  hasPlatformAccess: boolean,
): string {
  const personas: PersonaHint[] = [];
  const holds = (role: string) => roles.includes(role);

  if (holds("admin")) personas.push("admin");
  // Admins and owners may cover the coach surface (#632), mirroring
  // COACH_SURFACE_ROLES in lib/auth/coach-supervisor.ts.
  if (
    holds("coach") ||
    holds("assistant_coach") ||
    holds("admin") ||
    holds("owner")
  ) {
    personas.push("coach");
  }
  if (holds("parent")) personas.push("parent");
  if (holds("student")) personas.push("student");
  if (holds("owner")) personas.push("owner");
  if (hasPlatformAccess) personas.push("platform");

  return personas.join(",");
}

function homeForPersonas(personas: readonly PersonaHint[]): string | null {
  for (const [persona, home] of PERSONA_HOMES) {
    if (personas.includes(persona)) return home;
  }
  return null;
}

/**
 * Where this request should be sent instead, or null to let it through.
 *
 * Fails open on purpose: only two situations redirect — no session cookie of
 * any kind (→ `/login` carrying the return path) and a hint that names
 * personas but not this one (→ that user's own home).
 */
export function decidePersonaRedirect(
  request: PersonaRouteRequest,
): string | null {
  if (request.bypassAuth) return null;

  const persona = personaForPath(request.pathname);
  if (!persona) return null;

  const personas = parsePersonaHint(request.personaHint);
  const signedIn = request.hasIdentity === true || personas.length > 0;
  if (!signedIn) {
    const returnTo = `${request.pathname}${request.search ?? ""}`;
    return `/login?returnTo=${encodeURIComponent(returnTo)}`;
  }

  if (personas.length === 0) return null;
  if (personas.includes(persona)) return null;

  const home = homeForPersonas(personas);
  if (!home) return null;
  return `${home}?access_denied=${persona}`;
}
