/**
 * Sections inside one waiver body. Mirrors the backend rule in
 * `contexts/onboarding/domain/waiver_sections.py`: a line starting `## `
 * begins a section; `[initials]`, `[adult]` and `[minor]` at the end of the
 * heading mark it. Text before the first heading is an untitled section.
 */

export type WaiverAudience = "all" | "adult" | "minor";
export type SigningPath = "adult" | "minor";

export interface WaiverSection {
  key: string;
  heading: string | null;
  body: string;
  initials: boolean;
  audience: WaiverAudience;
}

const HEADING = /^##\s+(.*)$/;
const TAG = /\[(initials|adult|minor)\]/gi;
const INITIALS = /^[A-Za-z]{1,4}$/;

export function parseWaiverSections(body: string | null | undefined): WaiverSection[] {
  const sections: WaiverSection[] = [];
  let heading: string | null = null;
  let tags = new Set<string>();
  let lines: string[] = [];
  const flush = () => {
    const text = lines.join("\n").trim();
    if (heading === null && !text) return;
    sections.push({
      key: `s${sections.length + 1}`,
      heading,
      body: text,
      initials: tags.has("initials"),
      audience: tags.has("adult") ? "adult" : tags.has("minor") ? "minor" : "all",
    });
  };
  for (const line of (body ?? "").split(/\r?\n/)) {
    const match = HEADING.exec(line);
    if (match) {
      flush();
      const raw = match[1];
      tags = new Set(Array.from(raw.matchAll(TAG), (m) => m[1].toLowerCase()));
      heading = raw.replace(TAG, "").trim() || null;
      lines = [];
    } else {
      lines.push(line);
    }
  }
  flush();
  return sections;
}

export function hasAgePaths(sections: ReadonlyArray<WaiverSection>): boolean {
  return sections.some((section) => section.audience !== "all");
}

/** Keys of the initialled sections that apply to any of these signing paths. */
export function initialsNeeded(
  sections: ReadonlyArray<WaiverSection>,
  paths: ReadonlyArray<SigningPath | null>,
): string[] {
  return sections
    .filter(
      (section) =>
        section.initials &&
        (section.audience === "all" || paths.includes(section.audience)),
    )
    .map((section) => section.key);
}

export function initialsComplete(
  needed: ReadonlyArray<string>,
  given: Readonly<Record<string, string>> | undefined,
): boolean {
  return needed.every((key) => INITIALS.test((given?.[key] ?? "").trim()));
}

/** "adult" at 18 or over on `day`, "minor" below; null without a readable date. */
export function signingPathFor(dateOfBirth: string | null | undefined, day: Date): SigningPath | null {
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(dateOfBirth ?? "");
  if (!match) return null;
  const [year, month, date] = [Number(match[1]), Number(match[2]), Number(match[3])];
  const beforeBirthday =
    day.getUTCMonth() + 1 < month || (day.getUTCMonth() + 1 === month && day.getUTCDate() < date);
  return day.getUTCFullYear() - year - (beforeBirthday ? 1 : 0) >= 18 ? "adult" : "minor";
}
