import { apiFetch } from "./client";

export interface ConsumeMagicLinkResult {
  custom_token: string;
  next_path: string;
}

/**
 * Redeem a one-time parent magic-link token.
 *
 * POST (never GET) so an e-mail security scanner's prefetch cannot burn the
 * token before the parent clicks. The tenant is resolved on the backend from
 * the request host, so no auth header or academy id is needed here — the caller
 * is unauthenticated until the returned custom token is exchanged for a session.
 *
 * Throws an `ApiError` (with `.status`) on failure: 410 = expired, 401 =
 * invalid/used/tenant-mismatch.
 */
export function consumeMagicLink(token: string): Promise<ConsumeMagicLinkResult> {
  return apiFetch<ConsumeMagicLinkResult>("/magic-link/consume", {
    method: "POST",
    body: JSON.stringify({ token }),
    dedup: false,
  });
}
