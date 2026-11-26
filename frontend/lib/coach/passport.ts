import type { CoachPassport } from "@/lib/api/curriculum";

/** "Level 2 · Grip & Control · 4 of 6 passed" from the coach passport header. */
export function passportLevelLine(p: CoachPassport): string {
  const level = p.level_sequence != null ? `Level ${p.level_sequence}` : "";
  const name = p.level_name && p.level_name !== level ? p.level_name : "";
  return [level, name, `${p.passed_count} of ${p.total_count} passed`].filter(Boolean).join(" · ");
}
