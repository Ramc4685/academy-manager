/**
 * Skill-ladder draft (AI strategy Phase 2 B1): the pure parts of the card.
 *
 * The draft lives in component state until the owner chooses "Save to
 * program"; `saveLadderDraft` then walks it in order through the existing
 * create level / skill / criterion calls. Nothing is saved before that.
 */

import type { DraftLevel, DraftSkill, Level, Skill, SkillCriterion } from "@/lib/api/curriculum";

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

/**
 * Levels go after the program's last existing sequence (not its count, which
 * collides when a level was deleted); skills and criteria keep draft order.
 *
 * Every created row is recorded on the draft (`levelId`, `skillId`,
 * `criteriaSaved`) through `onProgress`, and rows that carry a record are
 * skipped, so Save after a failure resumes at the exact call that failed
 * instead of re-creating a level that already landed. `onLevelSaved` fires
 * once per fully saved level so the caller can drop it from the draft.
 */
export async function saveLadderDraft(
  programId: string,
  levels: DraftLevel[],
  lastLevelSequence: number,
  api: LadderSaveApi,
  onLevelSaved?: (index: number) => void,
  onProgress?: (index: number, level: DraftLevel) => void,
): Promise<void> {
  for (const [li, level] of levels.entries()) {
    let current = level;
    const record = (patch: (level: DraftLevel) => DraftLevel) => {
      current = patch(current);
      onProgress?.(li, current);
    };
    let levelId = level.levelId;
    if (!levelId) {
      const saved = await api.createLevel(programId, {
        name: level.name.trim(),
        description: level.description.trim(),
        sequence: lastLevelSequence + li + 1,
      });
      levelId = saved.level_id;
      record((l) => ({ ...l, levelId }));
    }
    for (const [si, skill] of current.skills.entries()) {
      const recordSkill = (patch: (skill: DraftSkill) => DraftSkill) =>
        record((l) => ({ ...l, skills: l.skills.map((s, i) => (i === si ? patch(s) : s)) }));
      let skillId = skill.skillId;
      if (!skillId) {
        const savedSkill = await api.createSkill(levelId, {
          program_id: programId,
          sequence: si + 1,
          name: skill.name.trim(),
          description: skill.description.trim(),
          is_required: skill.is_required,
          scoring_type: skill.scoring_type,
        });
        skillId = savedSkill.skill_id;
        recordSkill((s) => ({ ...s, skillId }));
      }
      // shortcut: criteria are posted in order, so a count marks the saved ones;
      // removing an already-saved criterion before a retry skips the next unsaved
      // one. Switch to a per-criterion flag if the rows become editable mid-save.
      for (const [ci, criterion] of skill.criteria.entries()) {
        if (ci < (skill.criteriaSaved ?? 0)) continue;
        await api.addCriterion(skillId, {
          level_id: levelId,
          program_id: programId,
          description: criterion.trim(),
          display_order: ci,
        });
        recordSkill((s) => ({ ...s, criteriaSaved: ci + 1 }));
      }
    }
    onLevelSaved?.(li);
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
