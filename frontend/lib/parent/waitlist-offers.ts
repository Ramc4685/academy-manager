/**
 * Waitlist seat offers on the parent Requests page (#828, X2).
 *
 * Pure so the countdown wording and the "what happened to my offer" copy can
 * be tested without rendering the page. The backend decides whether an offer
 * is still open; these helpers only phrase its answer.
 */

import type { ApiError } from "@/lib/api/client";
import type { ParentWaitlistEntry } from "@/lib/api/parent";

const MINUTE = 60_000;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;

/** Milliseconds left on an offer; 0 once the deadline has passed. */
export function msUntil(iso: string | null, now: number): number {
  if (!iso) return 0;
  const deadline = Date.parse(iso);
  if (Number.isNaN(deadline)) return 0;
  return Math.max(0, deadline - now);
}

/**
 * "2 days 5 hours left", "3 hours 12 minutes left", "8 minutes left".
 * Two units at most: a family deciding about a class needs the gist, and a
 * seconds counter only adds anxiety.
 */
export function formatCountdown(ms: number): string {
  if (ms <= 0) return "Offer closed";
  if (ms < MINUTE) return "Less than a minute left";
  const days = Math.floor(ms / DAY);
  const hours = Math.floor((ms % DAY) / HOUR);
  const minutes = Math.floor((ms % HOUR) / MINUTE);
  const unit = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`;
  if (days > 0) return `${unit(days, "day")}${hours ? ` ${unit(hours, "hour")}` : ""} left`;
  if (hours > 0) return `${unit(hours, "hour")}${minutes ? ` ${unit(minutes, "minute")}` : ""} left`;
  return `${unit(minutes, "minute")} left`;
}

/** Under a day left: worth an amber nudge rather than the calm default. */
export function isUrgent(ms: number): boolean {
  return ms > 0 && ms < DAY;
}

/**
 * An offer the list still calls `offered` can be past its deadline between
 * the deadline and the hourly sweep. Show it as closed rather than offering a
 * button the backend will refuse.
 */
export function offerIsOpen(entry: ParentWaitlistEntry, now: number): boolean {
  return entry.status === "offered" && msUntil(entry.offer_expires_at, now) > 0;
}

export type OfferFailure = "expired" | "taken" | "seat_gone" | "not_found" | "unknown";

/** Map the backend's refusal onto the story the family is told. */
export function classifyOfferError(error: unknown): OfferFailure {
  const code = (error as Partial<ApiError> | null)?.code;
  if (code === "Enrollment.WaitlistOfferExpired") return "expired";
  if (code === "Enrollment.WaitlistOfferNotOpen") return "taken";
  // X2: the class filled up again before the family confirmed. They are
  // back at the front of the waitlist, not dropped from it.
  if (code === "Enrollment.WaitlistOfferSeatUnavailable") return "seat_gone";
  if (code === "Enrollment.WaitlistOfferNotFound") return "not_found";
  return "unknown";
}

export function offerFailureMessage(failure: OfferFailure): string {
  switch (failure) {
    case "expired":
      return "This offer has expired, and the seat has gone to the next family on the waitlist. Please contact the academy if you would still like a place.";
    case "taken":
      return "This offer is no longer open. It may already have been confirmed or declined.";
    case "seat_gone":
      return "Sorry, the seat is no longer available. You are still first on the waitlist, and we will email you as soon as another seat opens.";
    case "not_found":
      return "We could not find this offer on your account. Check that you are signed in as the parent the email was sent to.";
    default:
      return "Something went wrong. Please try again, or contact the academy.";
  }
}

/** Offers first (soonest deadline first), then waiting rows, then closed ones. */
export function sortWaitlistEntries(entries: ParentWaitlistEntry[]): ParentWaitlistEntry[] {
  const rank = { offered: 0, waiting: 1, expired: 2 } as const;
  return [...entries].sort((a, b) => {
    const byStatus = rank[a.status] - rank[b.status];
    if (byStatus !== 0) return byStatus;
    return (a.offer_expires_at ?? a.joined_at).localeCompare(b.offer_expires_at ?? b.joined_at);
  });
}
