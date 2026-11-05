/**
 * B6: the coach types what they saw; the model maps it to one criterion of the
 * child's current level and phrases it for the parent. The draft only ever
 * prefills the existing skill-note form; saving that note is the approval.
 *
 * Pure functions in the node vitest environment: no React, no network.
 */

/** Mirrors the backend's OBSERVATION_MAX_CHARS. */
export const OBSERVATION_MAX = 500;

export interface TechniqueObservationDraft {
  criterion_id: string;
  skill_id: string;
  skill_name: string;
  parent_sentence: string;
  coach_summary: string;
}

/** What the draft puts into the existing note form. */
export interface PrefilledNote {
  skillId: string;
  body: string;
  hint: string;
}

export function noteFromDraft(draft: TechniqueObservationDraft): PrefilledNote {
  return {
    skillId: draft.skill_id,
    body: `${draft.parent_sentence.trim()}\n\nCoach summary: ${draft.coach_summary.trim()}`,
    hint: `AI suggested: ${draft.skill_name}, edit before saving`,
  };
}

/** The plain sentence for each way the draft route refuses. */
export function techniqueDraftErrorMessage(status: number | undefined): string {
  switch (status) {
    case 503:
      return "AI notes are not enabled for this academy yet";
    case 403:
      return "AI notes are part of the Growth plan";
    case 429:
      return "This academy has used its AI drafts for the month";
    case 502:
      return "The suggestion could not be read, try again";
    case 409:
      return "This student has no current level with criteria to match";
    default:
      return "Couldn't draft from that, try again";
  }
}
