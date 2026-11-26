/** S22: plain words for the sign-up wizard. Presentation only, no pricing maths. */

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

export function formatUsd(cents: number): string {
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(cents / 100);
}

/** "$80.00 per month", or "Free" for a free class. */
export function monthlyPriceLabel(cents: number): string {
  return cents > 0 ? `${formatUsd(cents)} per month` : "Free";
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
