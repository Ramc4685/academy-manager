import type { SkillBoardCell, SkillBoardSkill } from "@/lib/api/curriculum";

// Matches the backend default when an N_TRIES skill stores no count.
const DEFAULT_PASS_TRIES = 3;

export function passTries(skill: Pick<SkillBoardSkill, "pass_tries">): number {
  return skill.pass_tries ?? DEFAULT_PASS_TRIES;
}

/** One line under "Who got it?" saying what a tap does for this skill. */
export function passRuleLine(skill: Pick<SkillBoardSkill, "pass_rule" | "pass_tries">): string {
  switch (skill.pass_rule) {
    case "N_TRIES":
      return `Passes after ${passTries(skill)} taps, on any days. Each tap counts one try.`;
    case "LEAD_COACH":
      return "A lead coach signs this one off.";
    default:
      return "One tap passes it.";
  }
}

/** The chip on a row that has not passed yet: "Tap", "1 of 3" or "Lead coach". */
export function passRuleChip(
  skill: Pick<SkillBoardSkill, "pass_rule" | "pass_tries">,
  cell: Pick<SkillBoardCell, "tries"> | undefined,
): string {
  if (skill.pass_rule === "N_TRIES") return `${cell?.tries ?? 0} of ${passTries(skill)}`;
  if (skill.pass_rule === "LEAD_COACH") return "Lead coach";
  return "Tap";
}

/** Assistants cannot pass a lead-only skill, so its taps are not offered to them. */
export function needsLead(
  skill: Pick<SkillBoardSkill, "pass_rule">,
  assistant: boolean,
): boolean {
  return assistant && skill.pass_rule === "LEAD_COACH";
}
