/**
 * S66 "Coach is sick": the words the review and result steps show, kept
 * apart from the modal so each line is unit-tested. No money arithmetic here:
 * every amount comes from the server's cancel preview.
 */

import type { CoverOptions, CreditMissedClassResponse } from "@/lib/api/admin";
import { formatInAcademyZone } from "@/lib/format/academy-time";
import { formatCents } from "@/lib/money";

export type DateChoice =
  | { kind: "cover"; coachId: string | null }
  | { kind: "cancel" }
  | { kind: "leave" };

export const DEFAULT_CANCEL_REASON = "Coach unwell";

export function classDateLabel(iso: string, timezone: string | null | undefined): string {
  return formatInAcademyZone(iso, timezone, {
    weekday: "short",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

export function familiesEmailed(opt: CoverOptions): string[] {
  return opt.families.filter((f) => f.has_email).map((f) => f.family_name);
}

/** The review card for a date set to "Assign cover". */
export function coverReviewLines(opt: CoverOptions, coachId: string, notify: boolean): string[] {
  const cover = opt.free.find((c) => c.coach_id === coachId)?.name ?? "The cover coach";
  const lines = [`${cover} covers for ${opt.scheduled_coach.name}.`, `${cover} is told in the app.`];
  if (!notify) {
    lines.push("Families are not told.");
    return lines;
  }
  const emailed = familiesEmailed(opt);
  lines.push(
    emailed.length === 0
      ? "No family has an email address; they see the notice in the app."
      : `${emailed.length} ${emailed.length === 1 ? "family is" : "families are"} emailed: ${emailed.join(", ")}`,
  );
  return lines;
}

/** One line per family in a cancel review: who, and what they are credited. */
export function creditRows(preview: CreditMissedClassResponse): { who: string; credit: string }[] {
  return (preview.families ?? []).map((f) => ({
    who: f.student_name ?? "A student",
    credit:
      f.amount_cents > 0
        ? formatCents(f.amount_cents)
        : f.outcome === "already_credited"
          ? "already credited"
          : "no credit",
  }));
}

export function creditTotal(preview: CreditMissedClassResponse): string {
  return formatCents(preview.credit_total_cents);
}

/** Every chosen date has what it needs before Confirm is offered. */
export function readyToConfirm(
  choices: Record<string, DateChoice>,
  previews: Record<string, CreditMissedClassResponse | undefined>,
  reasons: Record<string, string>,
): boolean {
  const entries = Object.entries(choices);
  if (entries.length === 0 || entries.every(([, c]) => c.kind === "leave")) return false;
  return entries.every(([id, c]) => {
    if (c.kind === "cover") return Boolean(c.coachId);
    if (c.kind === "cancel") {
      const preview = previews[id];
      return Boolean(preview && !preview.schedule_changed && (reasons[id] ?? "").trim());
    }
    return true;
  });
}

export function coverResultLine(title: string, cover: string, notified: number, notify: boolean): string {
  const told = notify ? ` ${notified} ${notified === 1 ? "family" : "families"} emailed.` : "";
  return `${title}: ${cover} is covering.${told}`;
}

export function cancelResultLine(
  title: string,
  credited: number,
  totalCents: number,
  notified: boolean,
): string {
  const credit =
    credited > 0
      ? ` ${credited} ${credited === 1 ? "family" : "families"} credited ${formatCents(totalCents)}.`
      : "";
  return `${title}: cancelled.${credit}${notified ? " Families and the coach were emailed." : ""}`;
}
