"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  addCriterion,
  createLevel,
  createSkill,
  draftSkillLadder,
  getAiStatus,
  SKILL_SCORING_TYPES,
  type DraftLevel,
  type SkillScoringType,
} from "@/lib/api/curriculum";
import {
  ladderDraftErrorMessage,
  ladderDraftIsSavable,
  patchLevel,
  saveLadderDraft,
} from "@/lib/admin/skill-ladder-draft";
import { Button } from "@/components/ds/button";
import { Card } from "@/components/ds/card";
import { queryKeys } from "@/lib/query/keys";

const INPUT = "rounded-md border border-neutral-300 px-2 py-1.5 text-sm focus:border-blue-500 focus:outline-none";

/**
 * "Draft a skill ladder with AI" (AI strategy Phase 2 B1). Shown only when
 * GET /admin/ai/status says the academy has a model port. The draft is
 * editable rows in local state; nothing reaches the program until the owner
 * chooses "Save to program", which walks the existing create calls.
 */
export function SkillLadderDraftCard({
  programId,
  lastLevelSequence,
}: {
  programId: string;
  lastLevelSequence: number;
}) {
  const queryClient = useQueryClient();
  const status = useQuery({ queryKey: queryKeys.admin.aiStatus(), queryFn: getAiStatus });

  const [ageBand, setAgeBand] = useState("");
  const [levelCount, setLevelCount] = useState(4);
  const [notes, setNotes] = useState("");
  const [levels, setLevels] = useState<DraftLevel[] | null>(null);

  const draft = useMutation({
    mutationFn: () =>
      draftSkillLadder(programId, { age_band: ageBand.trim(), level_count: levelCount, notes }),
    onSuccess: (result) => setLevels(result.levels),
  });

  const save = useMutation({
    mutationFn: () =>
      saveLadderDraft(
        programId,
        levels ?? [],
        lastLevelSequence,
        { createLevel, createSkill, addCriterion },
        // Drop each level once it lands; the one being saved is always first.
        () => setLevels((prev) => prev?.slice(1) ?? null),
        // Record each created id on it, so Save after a failure skips what already landed.
        (_, level) => setLevels((prev) => (prev ? patchLevel(prev, 0, () => level) : prev)),
      ),
    onSuccess: () => setLevels(null),
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: ["admin", "pathway", programId] });
    },
  });

  if (status.data?.enabled !== true) return null;

  return (
    <Card p={20}>
      <div data-testid="skill-ladder-draft-card" className="space-y-3">
        <div>
          <h2 className="text-sm font-semibold">Draft a skill ladder with AI</h2>
          <p className="mt-1 text-xs text-neutral-500">
            Drafts levels, skills and observable criteria for {" "}
            <span className="font-medium">this program&apos;s sport</span>. Nothing is saved
            until you choose Save to program.
          </p>
        </div>

        <div className="grid gap-2 sm:grid-cols-[1fr_auto]">
          <label className="text-xs text-neutral-600">
            Age band
            <input
              type="text"
              value={ageBand}
              onChange={(e) => setAgeBand(e.target.value)}
              placeholder="e.g. 8-10"
              maxLength={30}
              className={`mt-1 w-full ${INPUT}`}
            />
          </label>
          <label className="text-xs text-neutral-600">
            Levels
            <select
              value={levelCount}
              onChange={(e) => setLevelCount(Number(e.target.value))}
              className={`mt-1 block ${INPUT}`}
            >
              {[2, 3, 4, 5, 6].map((n) => (
                <option key={n} value={n}>
                  {n}
                </option>
              ))}
            </select>
          </label>
        </div>
        <label className="block text-xs text-neutral-600">
          Notes about your academy&apos;s style (optional)
          <textarea
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            maxLength={500}
            rows={2}
            className={`mt-1 w-full ${INPUT}`}
          />
        </label>
        {draft.isError && (
          <p role="alert" className="text-xs text-red-600">
            {ladderDraftErrorMessage(draft.error)}
          </p>
        )}
        <div className="flex justify-end">
          <Button
            variant="secondary"
            size="sm"
            disabled={!ageBand.trim() || draft.isPending || save.isPending}
            onClick={() => draft.mutate()}
          >
            {draft.isPending ? "Drafting..." : levels ? "Draft again" : "Draft"}
          </Button>
        </div>

        {levels && (
          <div className="space-y-3 border-t border-neutral-200 pt-3 dark:border-neutral-800">
            {levels.map((level, li) => (
              <DraftLevelRows
                key={li}
                level={level}
                onChange={(patch) => setLevels(patchLevel(levels, li, patch))}
                onRemove={() => setLevels(levels.filter((_, i) => i !== li))}
              />
            ))}
            {save.isError && (
              <p role="alert" className="text-xs text-red-600">
                Saving stopped part way; what already landed is in the program below. Save again
                continues from the row that failed.
              </p>
            )}
            <div className="flex items-center justify-end gap-2">
              <span className="text-xs text-neutral-500">Nothing is saved until you choose Save to program.</span>
              <Button variant="secondary" size="sm" onClick={() => setLevels(null)}>
                Discard
              </Button>
              <Button
                variant="primary"
                size="sm"
                disabled={!ladderDraftIsSavable(levels) || save.isPending}
                onClick={() => save.mutate()}
              >
                {save.isPending ? "Saving..." : "Save to program"}
              </Button>
            </div>
          </div>
        )}
      </div>
    </Card>
  );
}

function DraftLevelRows({
  level,
  onChange,
  onRemove,
}: {
  level: DraftLevel;
  onChange: (patch: (level: DraftLevel) => DraftLevel) => void;
  onRemove: () => void;
}) {
  const setSkill = (si: number, patch: (s: DraftLevel["skills"][number]) => DraftLevel["skills"][number]) =>
    onChange((l) => ({ ...l, skills: l.skills.map((s, i) => (i === si ? patch(s) : s)) }));

  return (
    <div className="rounded-md border border-neutral-200 p-3 dark:border-neutral-800">
      <div className="flex items-start gap-2">
        <input
          type="text"
          aria-label="Level name"
          value={level.name}
          onChange={(e) => onChange((l) => ({ ...l, name: e.target.value }))}
          className={`w-48 font-semibold ${INPUT}`}
        />
        <input
          type="text"
          aria-label="Level description"
          value={level.description}
          onChange={(e) => onChange((l) => ({ ...l, description: e.target.value }))}
          className={`flex-1 ${INPUT}`}
        />
        <Button variant="ghost" size="sm" onClick={onRemove} aria-label="Remove level">
          Remove
        </Button>
      </div>
      <div className="mt-2 space-y-2 pl-4">
        {level.skills.map((skill, si) => (
          <div key={si} className="space-y-1">
            <div className="flex items-start gap-2">
              <input
                type="text"
                aria-label="Skill name"
                value={skill.name}
                onChange={(e) => setSkill(si, (s) => ({ ...s, name: e.target.value }))}
                className={`w-44 ${INPUT}`}
              />
              <input
                type="text"
                aria-label="Skill description"
                value={skill.description}
                onChange={(e) => setSkill(si, (s) => ({ ...s, description: e.target.value }))}
                className={`flex-1 ${INPUT}`}
              />
              <select
                aria-label="Scoring type"
                value={skill.scoring_type}
                onChange={(e) =>
                  setSkill(si, (s) => ({ ...s, scoring_type: e.target.value as SkillScoringType }))
                }
                className={INPUT}
              >
                {SKILL_SCORING_TYPES.map((t) => (
                  <option key={t.value} value={t.value}>
                    {t.label}
                  </option>
                ))}
              </select>
              <label className="flex items-center gap-1 text-xs">
                <input
                  type="checkbox"
                  checked={skill.is_required}
                  onChange={(e) => setSkill(si, (s) => ({ ...s, is_required: e.target.checked }))}
                />
                Required
              </label>
              <Button
                variant="ghost"
                size="sm"
                aria-label="Remove skill"
                onClick={() =>
                  onChange((l) => ({ ...l, skills: l.skills.filter((_, i) => i !== si) }))
                }
              >
                Remove
              </Button>
            </div>
            <ul className="space-y-1 pl-4">
              {skill.criteria.map((criterion, ci) => (
                <li key={ci} className="flex items-center gap-2">
                  <input
                    type="text"
                    aria-label="Criterion"
                    value={criterion}
                    onChange={(e) =>
                      setSkill(si, (s) => ({
                        ...s,
                        criteria: s.criteria.map((c, i) => (i === ci ? e.target.value : c)),
                      }))
                    }
                    className={`flex-1 text-xs ${INPUT}`}
                  />
                  <button
                    type="button"
                    aria-label="Remove criterion"
                    onClick={() =>
                      setSkill(si, (s) => ({ ...s, criteria: s.criteria.filter((_, i) => i !== ci) }))
                    }
                    className="text-xs text-neutral-500 hover:underline"
                  >
                    Remove
                  </button>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
    </div>
  );
}
