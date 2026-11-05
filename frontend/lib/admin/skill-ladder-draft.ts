/**
 * Skill-ladder draft (AI strategy Phase 2 B1): the pure parts of the card.
 *
 * The draft lives in component state until the owner chooses "Save to
 * program"; `saveLadderDraft` then walks it in order through the existing
 * create level / skill / criterion calls. Nothing is saved before that.
 */

import type { DraftLevel, Level, Skill, SkillCriterion } from "@/lib/api/curriculum";

export interface LadderSaveApi {
  createLevel: (
    programId: string,
    body: { name: string; description: string; sequence: number },
  ) => Promise<Pick<Level, "level_id">>;
  createSkill: (
    levelId: string,
    body: {
      program_id: string;
      sequence: number;
      name: string;
      description: string;
      is_required: boolean;
      scoring_type: DraftLevel["skills"][number]["scoring_type"];
    },
  ) => Promise<Pick<Skill, "skill_id">>;
  addCriterion: (
    skillId: string,
    body: { level_id: string; program_id: string; description: string; display_order: number },
  ) => Promise<Pick<SkillCriterion, "criterion_id">>;
}

/** Levels go after the program's existing ones; skills and criteria keep draft order. */
export async function saveLadderDraft(
  programId: string,
  levels: DraftLevel[],
  existingLevelCount: number,
  api: LadderSaveApi,
): Promise<void> {
  for (const [li, level] of levels.entries()) {
    const saved = await api.createLevel(programId, {
      name: level.name.trim(),
      description: level.description.trim(),
      sequence: existingLevelCount + li + 1,
    });
    for (const [si, skill] of level.skills.entries()) {
      const savedSkill = await api.createSkill(saved.level_id, {
        program_id: programId,
        sequence: si + 1,
        name: skill.name.trim(),
        description: skill.description.trim(),
        is_required: skill.is_required,
        scoring_type: skill.scoring_type,
      });
      for (const [ci, criterion] of skill.criteria.entries()) {
        await api.addCriterion(savedSkill.skill_id, {
          level_id: saved.level_id,
          program_id: programId,
          description: criterion.trim(),
          display_order: ci,
        });
      }
    }
  }
}

/** A draft can be saved when every row the owner kept still has a name. */
export function ladderDraftIsSavable(levels: DraftLevel[]): boolean {
  return (
    levels.length > 0 &&
    levels.every(
      (level) =>
        level.name.trim() &&
        level.skills.length > 0 &&
        level.skills.every(
          (skill) => skill.name.trim() && skill.criteria.every((c) => c.trim()),
        ),
    )
  );
}

export function ladderDraftErrorMessage(error: unknown): string {
  const e = (error ?? {}) as { status?: number; code?: string };
  if (e.code === "Ai.Disabled") return "AI drafting is not enabled for this academy yet";
  if (e.code === "Ai.MonthlyCapReached") {
    return "This academy has used its AI drafts for the month";
  }
  if (e.status === 502) return "The draft could not be read, try again";
  return "The draft could not be made, try again";
}

export function patchLevel(
  levels: DraftLevel[],
  index: number,
  patch: (level: DraftLevel) => DraftLevel,
): DraftLevel[] {
  return levels.map((level, i) => (i === index ? patch(level) : level));
}
