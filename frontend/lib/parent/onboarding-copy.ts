/** S22: plain words for the sign-up wizard. Presentation only, no pricing maths. */

import { formatCents } from "@/lib/money";

export type SkillLevel = "beginner" | "intermediate" | "advanced";

export const SKILL_LEVEL_HINTS: Record<SkillLevel, string> = {
  beginner: "New, or played only a few times",
  intermediate: "Can rally and knows the rules",
  advanced: "Plays matches or competes",
};

const LEVEL_NAMES: Record<SkillLevel, string> = {
  beginner: "Beginner",
  intermediate: "Intermediate",
  advanced: "Advanced",
};

/** The level a class title names ("Tuesday Intermediate"), when it names exactly one. */
export function classTitleLevel(title: string): SkillLevel | null {
  const found = (Object.keys(LEVEL_NAMES) as SkillLevel[]).filter((level) =>
    new RegExp(`\\b${level}s?\\b`, "i").test(title),
  );
  return found.length === 1 ? found[0] : null;
}

/** A gentle note when the class is listed for another level; never blocks. */
export function classLevelNote(title: string, childLevel: string): string | null {
  const classLevel = classTitleLevel(title);
  if (!classLevel || !(childLevel in LEVEL_NAMES) || classLevel === childLevel) return null;
  return `This class is listed as ${LEVEL_NAMES[classLevel]}; you chose ${LEVEL_NAMES[childLevel as SkillLevel]}. You can still pick it.`;
}

/** "Beginner" on the Review step; an unchosen level says so instead of "—". */
export function skillLevelLabel(level: string): string {
  return LEVEL_NAMES[level as SkillLevel] ?? "level not given";
}

/**
 * The Review step's price lines. A $0 quote gets one plain line: "0 of 4
 * classes — monthly rate covers 4 classes" and "Starting next month: $0.00"
 * read as paid-class wording (S22 persona follow-up). Never "Free" (see below).
 */
export function reviewPriceLines(quote: {
  amount_due_cents: number;
  next_billing_amount_cents: number;
  message: string;
}): string[] {
  if (quote.amount_due_cents === 0 && quote.next_billing_amount_cents === 0) {
    return [`Price: ${monthlyPriceLabel(0)}. Nothing to pay at checkout.`];
  }
  return [
    `First month: ${formatCents(quote.amount_due_cents)} · ${quote.message}`,
    `Starting next month: ${monthlyPriceLabel(quote.next_billing_amount_cents)}`,
  ];
}

/**
 * "$80.00 per month". Never "Free": an unpriced class also reaches here as 0,
 * and only S42 knows whether a class is explicitly free.
 */
export function monthlyPriceLabel(cents: number): string {
  return `${formatCents(cents)} per month`;
}

/** The local calendar date as YYYY-MM-DD, for a date input's `max`. */
export function localIsoDate(now: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
}

export function dateOfBirthError(value: string, today: string): string | null {
  if (!value) return null;
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return "Enter the date of birth as a full date.";
  if (value > today) return "Date of birth can't be in the future.";
  return null;
}

/**
 * Above a returning family's waiver: each child is signed for separately (the
 * rule stays), so say why it is asked again and that the name is filled in.
 */
export function waiverPerChildNote(childFirstName: string): string {
  const child = childFirstName.trim() || "this child";
  return `Each child needs their own signed waiver, so this one is for ${child}. Your name is already filled in.`;
}
