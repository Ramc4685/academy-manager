/**
 * Pure helpers for the "What happened this month" card on the Reports page
 * (B5 month-close narrator). Data in, strings out, no React.
 */

import type { AdminMonthCloseNarrative } from "@/lib/api/admin";

const ERROR_COPY: Record<number, string> = {
  503: "AI summaries are not enabled for this academy yet",
  403: "AI summaries are part of the Growth plan",
  429: "This academy has used its AI drafts for the month",
  502: "The summary could not be checked against the numbers, try again",
};

export const NARRATIVE_FOOTNOTE =
  "Written by AI from the numbers above; it never calculates money.";

/** One plain sentence per failure; never the raw error. */
export function narrativeErrorCopy(error: unknown): string {
  const status =
    typeof error === "object" && error !== null && "status" in error
      ? (error as { status?: unknown }).status
      : undefined;
  return (typeof status === "number" && ERROR_COPY[status]) || "The summary could not be written, try again";
}

export interface FixFirstLink {
  key: string;
  text: string;
  href: string;
}

/**
 * The fix-first list as link rows: in the backend's order, blank rows dropped,
 * at most three. The backend already refused any href outside the month-close
 * view and its fixed admin pages, so nothing is re-validated here.
 */
export function fixFirstLinks(narrative: Pick<AdminMonthCloseNarrative, "fix_first">): FixFirstLink[] {
  return narrative.fix_first
    .filter((fix) => fix.text.trim() !== "" && fix.href.trim() !== "")
    .slice(0, 3)
    .map((fix, index) => ({ key: `${index}:${fix.href}`, text: fix.text.trim(), href: fix.href }));
}
