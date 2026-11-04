import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

import {
  IDENTITY_COOKIE,
  PERSONA_HINT_COOKIE,
  decidePersonaRedirect,
} from "@/lib/auth/persona-route-guard";

/**
 * Persona gate at the edge (#451).
 *
 * Settles the two obvious cases — no session at all, and a session whose
 * persona hint disagrees with the shell being opened — before the client
 * shell paints, so nobody watches a loading flicker on the way to a
 * redirect. Everything else falls through to the existing client guard.
 *
 * Runs on the Cloudflare Workers edge runtime via OpenNext: no Node APIs, no
 * backend call, only cookies already on the request. Keep the import graph
 * minimal for the same reason — `persona-route-guard` deliberately imports
 * nothing. The hint is advisory; the backend's 404-on-wrong-persona is the
 * real gate (see `backend/v2/shared/http/persona.py`).
 */
const E2E_BYPASS = process.env.NEXT_PUBLIC_E2E_AUTH_BYPASS === "1";

export function middleware(request: NextRequest): NextResponse {
  const redirectTo = decidePersonaRedirect({
    pathname: request.nextUrl.pathname,
    search: request.nextUrl.search,
    personaHint: request.cookies.get(PERSONA_HINT_COOKIE)?.value,
    hasIdentity: request.cookies.has(IDENTITY_COOKIE),
    bypassAuth: E2E_BYPASS,
  });

  if (!redirectTo) return NextResponse.next();
  return NextResponse.redirect(new URL(redirectTo, request.nextUrl));
}

// Next statically parses this object at build time, so the matcher has to be
// a literal — keep it identical to `PERSONA_PATH_MATCHER` in
// `lib/auth/persona-route-guard.ts`, which is what the unit tests pin.
export const config = {
  matcher: ["/admin/:path*", "/coach/:path*", "/parent/:path*", "/platform/:path*"],
};
