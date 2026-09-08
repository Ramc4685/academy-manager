/**
 * Presentation rules for the Billing Health header.
 *
 * The verdict itself is computed on the backend (spec 2026-09-07 §4.2) — the
 * page used to derive "System healthy" from backlog counts alone and could
 * render a green pill directly above a red "Parents cannot pay right now"
 * card. All that is left on this side is the state → tone mapping and the
 * truncation line, kept here so they can be tested without a browser.
 */

export type BillingHealthState = "blocked" | "attention" | "ok";

export interface HealthPill {
  /** Data attribute the e2e specs assert on. */
  tone: "red" | "amber" | "green";
  className: string;
}

const PILLS: Record<BillingHealthState, HealthPill> = {
  blocked: { tone: "red", className: "bg-red-50 text-red-700" },
  attention: { tone: "amber", className: "bg-amber-50 text-amber-800" },
  ok: { tone: "green", className: "bg-green-50 text-green-700" },
};

/**
 * Tone for a verdict state. An unrecognised state reads as `attention`, never
 * as healthy: a state we cannot interpret is not a state we can call fine.
 */
export function healthPillTone(state: string | null | undefined): HealthPill {
  if (state && state in PILLS) return PILLS[state as BillingHealthState];
  return PILLS.attention;
}

/**
 * "Showing the 50 most recent of 214 quarantined events." — the webhook list
 * route caps at 50 while the tile beside it shows the true aggregate count, so
 * say so rather than letting the two silently disagree.
 */
export function truncationLine(shown: number, total: number): string | null {
  if (total <= shown) return null;
  return `Showing the ${shown} most recent of ${total} quarantined events.`;
}
