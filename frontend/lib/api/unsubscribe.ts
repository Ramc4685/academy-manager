import { apiFetch } from "./client";

export interface EmailPreferenceState {
  campaigns_opted_out: boolean;
  digests_opted_out: boolean;
  /** Roster-change alerts for coaches and academy staff (#612). */
  notifications_opted_out: boolean;
}

/**
 * Read the preferences an emailed unsubscribe token points at.
 *
 * POST (never GET) for the same reason the magic-link consume route is a POST:
 * e-mail security scanners and link-preview bots issue GET prefetches, and a
 * GET that could mutate preferences would let a corporate mail scanner
 * unsubscribe families automatically. The token is the entire authority — the
 * caller is unauthenticated — and the tenant is resolved on the backend from
 * the request host, so no auth header or academy id is attached here.
 *
 * Throws an `ApiError` (with `.status`): 401 = forged/tampered/wrong-tenant
 * token, 404 = unsubscribe is not configured on this deployment, 400 = the
 * host did not resolve to an academy.
 */
export function previewUnsubscribe(token: string): Promise<EmailPreferenceState> {
  return apiFetch<EmailPreferenceState>("/unsubscribe/preview", {
    method: "POST",
    body: JSON.stringify({ token }),
    dedup: false,
  });
}

/**
 * Save the recipient's choices.
 *
 * Note there is deliberately no `transactional` field: invoices, dunning
 * notices and login links are not something a recipient can switch off, and
 * the backend rejects the key outright rather than ignoring it.
 */
export function confirmUnsubscribe(
  token: string,
  choices: { campaigns: boolean; digests: boolean; notifications: boolean },
): Promise<EmailPreferenceState> {
  return apiFetch<EmailPreferenceState>("/unsubscribe/confirm", {
    method: "POST",
    body: JSON.stringify({
      token,
      campaigns: choices.campaigns,
      digests: choices.digests,
      notifications: choices.notifications,
    }),
    dedup: false,
  });
}
