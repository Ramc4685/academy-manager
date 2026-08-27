/**
 * Open-redirect guard for Firebase's `continueUrl` action parameter.
 *
 * The backend sends `ActionCodeSettings` pointing at the recipient academy's
 * own portal, and Firebase echoes that back on the action link as
 * `continueUrl`. But it reaches us as a *query parameter*, so anyone can put
 * any URL there. Honouring it blindly would turn `/auth/action` into an open
 * redirect that bounces a just-authenticated parent off the academy's domain.
 *
 * Mirrors the same-site rule the magic-link flow applies to `next_path`.
 */

const FALLBACK_PATH = "/login";

export function safeContinuePath(continueUrl: string | null | undefined, origin: string): string {
  if (!continueUrl) return FALLBACK_PATH;
  try {
    const target = new URL(continueUrl, origin);
    if (target.origin !== origin) return FALLBACK_PATH;
    const path = `${target.pathname}${target.search}${target.hash}`;
    // `//evil.com` would be read as protocol-relative if ever re-resolved.
    if (!path.startsWith("/") || path.startsWith("//")) return FALLBACK_PATH;
    return path;
  } catch {
    return FALLBACK_PATH;
  }
}
