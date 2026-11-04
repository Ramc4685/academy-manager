/**
 * Criterion quick-tags for the coach's one-line mastery note.
 *
 * The skill board sends each skill's observable criteria ("Thumb is flat on
 * back of handle"). Tapping them writes the note as one templated sentence, so
 * the coach types nothing courtside. Which chips are "on" is read back from
 * the draft itself, so the coach's own edits and the chips never disagree.
 *
 * Pure functions in the node vitest environment: no React, no model call.
 */

/** Mirrors the backend's MASTERY_NOTE_MAX_CHARS. */
export const NOTE_MAX = 140;

const LEAD = "Nailed it today: ";

/** "Thumb is flat on back of handle." -> "thumb is flat on back of handle"; "V grip" keeps its capital. */
function cue(criterion: string): string {
  return criterion
    .trim()
    .replace(/\.$/, "")
    .replace(/^[A-Z](?=[a-z])/, (c) => c.toLowerCase());
}

function sentence(cues: string[]): string {
  const list =
    cues.length > 1 ? `${cues.slice(0, -1).join(", ")} and ${cues[cues.length - 1]}` : cues[0];
  return `${LEAD}${list}.`;
}

/**
 * The note for the tapped criteria, in curriculum order. Criteria that would
 * push the sentence past NOTE_MAX are left out, so the note stays whole.
 */
export function composeMasteryNote(picked: string[]): string {
  const kept: string[] = [];
  for (const c of picked.map(cue).filter(Boolean)) {
    if (sentence([...kept, c]).length > NOTE_MAX) break;
    kept.push(c);
  }
  return kept.length ? sentence(kept) : "";
}

/** The criteria the draft already says: the chips' pressed state. */
export function pickedCriteria(draft: string, criteria: string[]): string[] {
  return criteria.filter((c) => cue(c) !== "" && draft.includes(cue(c)));
}

/** Tap a chip: add or remove it, and rewrite the draft as the templated sentence. */
export function toggleCriterion(draft: string, criteria: string[], tapped: string): string {
  const picked = new Set(pickedCriteria(draft, criteria));
  if (picked.has(tapped)) picked.delete(tapped);
  else picked.add(tapped);
  return composeMasteryNote(criteria.filter((c) => picked.has(c)));
}
