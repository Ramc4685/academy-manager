/**
 * Human copy for a parent's self-cancel (issue #675).
 *
 * The API reports the policy's raw `effective_timing` token
 * (`immediate` | `end_of_period`) plus the instant the cancel takes effect.
 * Parents should read a sentence, not a token: with `end_of_period` the child
 * keeps their place through the last day of the month they paid for, and the
 * following month is not billed.
 */

import { formatAcademyDate } from "@/lib/format/academy-time";

export interface CancellationCopyInput {
  effective_timing: string;
  /** ISO instant the cancel takes effect; null when the API predates #675. */
  effective_at?: string | null | undefined;
}

function monthAfter(iso: string, academyTimezone: string | null | undefined): string {
  const instant = new Date(iso);
  if (Number.isNaN(instant.getTime())) return "";
  // The month-end instant sits a hair before midnight local; +1 day lands
  // squarely in the next month regardless of zone offset.
  const next = new Date(instant.getTime() + 24 * 60 * 60 * 1000);
  return new Intl.DateTimeFormat("en-US", {
    month: "long",
    timeZone: academyTimezone || undefined,
  }).format(next);
}

/** Sentence shown in the cancel dialog before the parent confirms. */
export function cancellationTimingCopy(
  input: CancellationCopyInput,
  academyTimezone: string | null | undefined,
): string {
  if (input.effective_timing !== "end_of_period") {
    return "Your child's enrollment ends today.";
  }
  if (!input.effective_at) {
    return "Your child keeps their place through the end of this billing period.";
  }
  const lastDay = formatAcademyDate(input.effective_at, academyTimezone);
  const next = monthAfter(input.effective_at, academyTimezone);
  const billing = next ? `; ${next} will not be billed` : "";
  return `Your child keeps their place through ${lastDay}${billing}.`;
}

/** Short label for a roster / enrollment row while the cancel is pending. */
export function pendingCancellationLabel(
  pendingCancellationAt: string | null | undefined,
  academyTimezone: string | null | undefined,
): string | null {
  if (!pendingCancellationAt) return null;
  const day = formatAcademyDate(pendingCancellationAt, academyTimezone);
  return day ? `Ends ${day}` : "Ending soon";
}

/** Toast title after the cancel request succeeded. */
export function cancellationResultTitle(status: string): string {
  return status === "pending_cancellation" ? "Cancellation scheduled" : "Enrollment cancelled";
}
