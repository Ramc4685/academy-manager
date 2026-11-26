"use client";

import { useState, type ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  addExternalRef,
  buildCreateSkillBody,
  createLevel,
  createSkill,
  getAdminPathwayDashboard,
  getFullPathway,
  getLevelUsage,
  listLessonCards,
  reorderLevels,
  reorderSkills,
  retireLevel,
  retireSkill,
  seedLessonCards,
  SKILL_PASS_RULES,
  SKILL_SCORING_TYPES,
  updateSkillPassRule,
  type ExternalLessonReference,
  type ExternalSource,
  type PathwayLevel,
  type SeedLessonCardsResult,
  type Skill,
  type SkillPassRule,
  type SkillScoringType,
} from "@/lib/api/curriculum";
import { DeleteLevelDialog } from "@/components/admin/curriculum/delete-level-dialog";
import { LevelColorPicker } from "@/components/admin/curriculum/level-color-picker";
import { SkillLadderDraftCard } from "@/components/admin/curriculum/skill-ladder-draft-card";
import { levelSwatch } from "@/lib/level-color";
import { Card } from "@/components/ds/card";
import { Button } from "@/components/ds/button";
import { ConfirmActionDialog } from "@/components/ds/confirm-action-dialog";
import { queryKeys } from "@/lib/query/keys";
import { defaultExternalSourceForSport, sourceTitlePlaceholder } from "@/lib/pathway-sport";

/**
 * The skill program editor (levels, skills, references, lesson cards). Moved
 * from /admin/pathway/[programId] into Settings -> Curriculum (Settings
 * overhaul Phase 3 PR 11).
 */
export function ProgramEditor({
  programId,
  onBack,
}: {
  programId: string;
  onBack?: () => void;
}) {
  const queryClient = useQueryClient();

  const { data, isLoading, isError } = useQuery({
    queryKey: ["admin", "pathway", programId],
    queryFn: () => getFullPathway(programId),
    enabled: Boolean(programId),
  });

  // Under the pathway key, so every pathway invalidation refreshes it too.
  const usage = useQuery({
    queryKey: ["admin", "pathway", programId, "level-usage"],
    queryFn: () => getLevelUsage(programId),
    enabled: Boolean(programId),
  });

  // Players on each level: a level with players cannot be retired.
  const { data: dashboard } = useQuery({
    queryKey: [...queryKeys.admin.pathwayDashboard(), programId],
    queryFn: () => getAdminPathwayDashboard(programId),
    enabled: Boolean(programId),
  });
  const playerCounts = new Map(dashboard?.levels.map((l) => [l.level_id, l.player_count]));

  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ["admin", "pathway", programId] });
    void queryClient.invalidateQueries({ queryKey: queryKeys.admin.pathwayDashboard() });
  };

  const moveLevel = useMutation({
    mutationFn: (ids: string[]) => reorderLevels(programId, ids),
    onSuccess: refresh,
  });

  const [showAddLevel, setShowAddLevel] = useState(false);
  const [levelName, setLevelName] = useState("");
  const [levelDescription, setLevelDescription] = useState("");

  const addLevelMutation = useMutation({
    mutationFn: () =>
      createLevel(programId, {
        name: levelName,
        description: levelDescription,
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["admin", "pathway", programId] });
      setShowAddLevel(false);
      setLevelName("");
      setLevelDescription("");
    },
  });

  if (isLoading) return <Skeleton />;

  if (isError || !data) {
    return (
      <p role="alert" className="rounded-md bg-red-50 p-3 text-sm text-red-700">
        Could not load pathway.
      </p>
    );
  }

  return (
    <section data-testid="admin-pathway-detail" className="space-y-6">
      {onBack && (
        <button
          type="button"
          data-testid="curriculum-back-to-programs"
          onClick={onBack}
          className="text-sm font-medium text-blue-700 hover:underline"
        >
          &larr; All programs
        </button>
      )}
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="text-2xl font-semibold">{data.program.name}</h2>
          <p className="mt-0.5 text-sm text-neutral-500">{data.program.sport}</p>
          {data.program.description && (
            <p className="mt-1 text-sm text-neutral-600">{data.program.description}</p>
          )}
        </div>
        <Button variant="primary" size="sm" onClick={() => setShowAddLevel((v) => !v)}>
          {showAddLevel ? "Cancel" : "Add Level"}
        </Button>
      </div>

      <LessonCardsPanel programId={programId} />

      <SkillLadderDraftCard
        programId={programId}
        lastLevelSequence={Math.max(0, ...data.levels.map((l) => l.level.sequence))}
      />

      {showAddLevel && (
        <Card p={20}>
          <h2 className="mb-3 text-sm font-semibold">New Level</h2>
          <div className="space-y-3">
            <input
              type="text"
              value={levelName}
              onChange={(e) => setLevelName(e.target.value)}
              placeholder="Level name (e.g. Beginner)"
              className="w-full rounded-md border border-neutral-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
            />
            <input
              type="text"
              value={levelDescription}
              onChange={(e) => setLevelDescription(e.target.value)}
              placeholder="Description (optional)"
              className="w-full rounded-md border border-neutral-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
            />
            {addLevelMutation.isError && (
              <p className="text-xs text-red-600">Failed to add level.</p>
            )}
            <div className="flex justify-end gap-2">
              <Button variant="secondary" size="sm" onClick={() => setShowAddLevel(false)}>
                Cancel
              </Button>
              <Button
                variant="primary"
                size="sm"
                disabled={!levelName.trim() || addLevelMutation.isPending}
                onClick={() => addLevelMutation.mutate()}
              >
                {addLevelMutation.isPending ? "Adding..." : "Add Level"}
              </Button>
            </div>
          </div>
        </Card>
      )}

      {data.levels.length === 0 ? (
        <p className="text-sm text-neutral-500">No levels yet. Add one to build the pathway.</p>
      ) : (
        <div className="space-y-4">
          {moveLevel.isError && (
            <p role="alert" className="text-sm text-red-600">
              {moveLevel.error.message || "Could not reorder the levels."}
            </p>
          )}
          {data.levels.map((pathwayLevel, index) => (
            <LevelAccordion
              key={pathwayLevel.level.level_id}
              pathwayLevel={pathwayLevel}
              isBadminton={data.program.sport.toLowerCase() === "badminton"}
              deletable={usage.data?.levels[pathwayLevel.level.level_id]?.deletable === true}
              playerCount={playerCounts.get(pathwayLevel.level.level_id)}
              move={
                <MoveButtons
                  label={`level ${pathwayLevel.level.name}`}
                  index={index}
                  count={data.levels.length}
                  disabled={moveLevel.isPending}
                  onMove={(offset) =>
                    moveLevel.mutate(swapped(data.levels.map((l) => l.level.level_id), index, offset))
                  }
                />
              }
              onSkillAdded={refresh}
            />
          ))}
        </div>
      )}
    </section>
  );
}

function LessonCardsPanel({ programId }: { programId: string }) {
  const queryClient = useQueryClient();

  const { data, isLoading } = useQuery({
    queryKey: queryKeys.admin.lessonCards(programId),
    queryFn: () => listLessonCards(programId),
    enabled: Boolean(programId),
  });

  const [lastResult, setLastResult] = useState<SeedLessonCardsResult | null>(null);

  const seedMutation = useMutation({
    mutationFn: () => seedLessonCards(programId),
    onSuccess: (result) => {
      setLastResult(result);
      void queryClient.invalidateQueries({
        queryKey: queryKeys.admin.lessonCards(programId),
      });
    },
  });

  const count = data?.count ?? 0;
  const seeded = count > 0;

  return (
    <Card p={20}>
      <div className="flex items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-2">
            <h2 className="text-sm font-semibold">Lesson cards</h2>
            {isLoading ? (
              <span className="rounded-full bg-neutral-100 px-2 py-0.5 text-[10px] font-medium text-neutral-400 dark:bg-neutral-800">
                Loading…
              </span>
            ) : (
              <span
                className={
                  seeded
                    ? "rounded-full bg-green-50 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider text-green-700"
                    : "rounded-full bg-neutral-100 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider text-neutral-500 dark:bg-neutral-800"
                }
              >
                {seeded ? `${count} cards seeded` : "Not seeded"}
              </span>
            )}
          </div>
          <p className="mt-1 text-xs text-neutral-500">
            Original-wording teaching cards mapping lessons to skills. Seeding is
            idempotent.
          </p>
          {lastResult && (
            <p className="mt-1 text-xs text-neutral-600" role="status">
              {lastResult.cards_created} created · {lastResult.cards_updated} updated
              · {lastResult.cards_unchanged} unchanged
            </p>
          )}
          {seedMutation.isError && (
            <p className="mt-1 text-xs text-red-600">Failed to seed lesson cards.</p>
          )}
        </div>
        <Button
          variant="secondary"
          size="sm"
          disabled={seedMutation.isPending}
          onClick={() => seedMutation.mutate()}
        >
          {seedMutation.isPending ? "Seeding…" : "Seed lesson cards"}
        </Button>
      </div>
    </Card>
  );
}

/** ids with the item at `index` moved one place by `offset` (-1 up, +1 down). */
export function swapped(ids: string[], index: number, offset: -1 | 1): string[] {
  const next = [...ids];
  [next[index], next[index + offset]] = [next[index + offset], next[index]];
  return next;
}

function MoveButtons({
  label,
  index,
  count,
  disabled,
  onMove,
}: {
  label: string;
  index: number;
  count: number;
  disabled: boolean;
  onMove: (offset: -1 | 1) => void;
}) {
  return (
    <>
      <button
        type="button"
        aria-label={`Move ${label} up`}
        disabled={disabled || index === 0}
        onClick={() => onMove(-1)}
        className="rounded px-1.5 text-xs text-neutral-500 hover:bg-neutral-100 disabled:opacity-40 dark:hover:bg-neutral-800"
      >
        ↑
      </button>
      <button
        type="button"
        aria-label={`Move ${label} down`}
        disabled={disabled || index === count - 1}
        onClick={() => onMove(1)}
        className="rounded px-1.5 text-xs text-neutral-500 hover:bg-neutral-100 disabled:opacity-40 dark:hover:bg-neutral-800"
      >
        ↓
      </button>
    </>
  );
}

function LevelAccordion({
  pathwayLevel,
  isBadminton,
  deletable,
  playerCount,
  move,
  onSkillAdded,
}: {
  pathwayLevel: PathwayLevel;
  isBadminton: boolean;
  deletable: boolean;
  /** Undefined until the dashboard loads; Retire waits for it. */
  playerCount: number | undefined;
  move: ReactNode;
  onSkillAdded: () => void;
}) {
  const [confirmRetire, setConfirmRetire] = useState(false);
  const [skillNotice, setSkillNotice] = useState<string | null>(null);
  const retire = useMutation({
    mutationFn: () => retireLevel(pathwayLevel.level.level_id),
    onSuccess: () => {
      setConfirmRetire(false);
      onSkillAdded();
    },
  });
  const moveSkill = useMutation({
    mutationFn: (ids: string[]) => reorderSkills(pathwayLevel.level.level_id, ids),
    onSuccess: onSkillAdded,
  });
  const [open, setOpen] = useState(true);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [showAddSkill, setShowAddSkill] = useState(false);
  const [skillName, setSkillName] = useState("");
  const [skillDescription, setSkillDescription] = useState("");
  const [skillRequired, setSkillRequired] = useState(true);
  const [skillScoringType, setSkillScoringType] = useState<SkillScoringType>("ATTEMPT_BASED");
  const [skillPassRule, setSkillPassRule] = useState<SkillPassRule>("ONE_TAP");
  const [skillPassTries, setSkillPassTries] = useState(3);

  const addSkillMutation = useMutation({
    mutationFn: () =>
      createSkill(
        pathwayLevel.level.level_id,
        buildCreateSkillBody(pathwayLevel.level, {
          name: skillName,
          description: skillDescription,
          is_required: skillRequired,
          scoring_type: skillScoringType,
          pass_rule: skillPassRule,
          pass_tries: skillPassTries,
        }),
      ),
    onSuccess: () => {
      onSkillAdded();
      setShowAddSkill(false);
      setSkillName("");
      setSkillDescription("");
    },
  });

  const { level, skills } = pathwayLevel;

  return (
    <div className="overflow-hidden rounded-lg border border-neutral-200 dark:border-neutral-800">
      {/* Level header */}
      <button
        className="flex w-full items-center justify-between bg-neutral-50 px-4 py-3 text-left hover:bg-neutral-100 dark:bg-neutral-900 dark:hover:bg-neutral-800"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
      >
        <div className="flex items-center gap-3">
          <span
            className="flex h-6 w-6 items-center justify-center rounded-full text-[11px] font-bold ring-1 ring-black/25"
            style={{
              background: levelSwatch(level.display_color).fill,
              color: levelSwatch(level.display_color).on,
            }}
          >
            {level.sequence}
          </span>
          <div className="min-w-0">
            <span className="font-semibold text-rally-base">{level.name}</span>
            {level.description && (
              <span className="block text-sm text-neutral-500 sm:ml-2 sm:inline">{level.description}</span>
            )}
          </div>
        </div>
        <div className="flex items-center gap-3">
          <span className="text-xs text-neutral-500">{skills.length} skill{skills.length !== 1 ? "s" : ""}</span>
          <svg
            width="14"
            height="14"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2.5"
            strokeLinecap="round"
            strokeLinejoin="round"
            className={`transition-transform ${open ? "rotate-90" : ""}`}
          >
            <polyline points="9 18 15 12 9 6" />
          </svg>
        </div>
      </button>

      {open && (
        <div className="divide-y divide-neutral-100 dark:divide-neutral-800">
          <div className="flex flex-wrap items-center gap-2 px-4 py-2">
            {move}
            <Button
              variant="secondary"
              size="sm"
              disabled={playerCount !== 0}
              onClick={() => setConfirmRetire(true)}
            >
              Retire level
            </Button>
            {playerCount !== undefined && playerCount > 0 && (
              <span className="text-xs text-neutral-500">
                {playerCount} player{playerCount !== 1 ? "s" : ""} on this level: move them before
                retiring it
              </span>
            )}
            {moveSkill.isError && (
              <span role="alert" className="text-xs text-red-600">
                {moveSkill.error.message || "Could not reorder the skills."}
              </span>
            )}
            {skillNotice && (
              <span role="status" className="text-xs text-neutral-600">
                {skillNotice}
              </span>
            )}
          </div>
          <ConfirmActionDialog
            open={confirmRetire}
            onOpenChange={(next) => {
              setConfirmRetire(next);
              if (!next) retire.reset();
            }}
            overline="Retire level"
            title={`Retire ${level.name}?`}
            consequence="The level leaves the pathway. Certificates already issued for it stay."
            confirmLabel="Retire level"
            pending={retire.isPending}
            error={retire.isError ? retire.error.message || "Could not retire the level." : null}
            onConfirm={() => retire.mutate()}
          />
          <LevelColorPicker level={level} onSaved={onSkillAdded} />
          {skills.length === 0 && !showAddSkill && (
            <p className="px-4 py-3 text-sm text-neutral-400">No skills yet.</p>
          )}

          {skills.map(({ skill, external_refs }, index) => (
            <SkillRow
              key={skill.skill_id}
              skill={skill}
              externalRefs={external_refs}
              isBadminton={isBadminton}
              onRefAdded={onSkillAdded}
              move={
                <MoveButtons
                  label={`skill ${skill.name}`}
                  index={index}
                  count={skills.length}
                  disabled={moveSkill.isPending}
                  onMove={(offset) =>
                    moveSkill.mutate(swapped(skills.map((s) => s.skill.skill_id), index, offset))
                  }
                />
              }
              onRetired={(queued) => {
                setSkillNotice(
                  queued > 0
                    ? `Skill retired. ${queued} student${queued !== 1 ? "s" : ""} queued for a level-up.`
                    : "Skill retired.",
                )
                onSkillAdded();
              }}
            />
          ))}

          {showAddSkill && (
            <div className="bg-blue-50 p-4 dark:bg-blue-950">
              <div className="space-y-2">
                <input
                  type="text"
                  value={skillName}
                  onChange={(e) => setSkillName(e.target.value)}
                  placeholder="Skill name"
                  className="w-full rounded-md border border-neutral-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
                />
                <input
                  type="text"
                  value={skillDescription}
                  onChange={(e) => setSkillDescription(e.target.value)}
                  placeholder="Description (optional)"
                  className="w-full rounded-md border border-neutral-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
                />
                <div className="flex items-center gap-4">
                  <label className="flex items-center gap-1.5 text-sm">
                    <input
                      type="checkbox"
                      checked={skillRequired}
                      onChange={(e) => setSkillRequired(e.target.checked)}
                      className="rounded"
                      aria-describedby="skill-required-hint"
                    />
                    Required
                  </label>
                  <span id="skill-required-hint" className="text-xs text-neutral-600">
                    {skillRequired
                      ? "A child needs this skill to move up a level."
                      : "Not required: a child can move up without this skill."}
                  </span>
                  <select
                    value={skillScoringType}
                    onChange={(e) => setSkillScoringType(e.target.value as SkillScoringType)}
                    className="rounded-md border border-neutral-300 px-2 py-1 text-sm focus:outline-none"
                  >
                    {SKILL_SCORING_TYPES.map((t) => (
                      <option key={t.value} value={t.value}>
                        {t.label}
                      </option>
                    ))}
                  </select>
                  <PassRuleFields
                    rule={skillPassRule}
                    tries={skillPassTries}
                    onRule={setSkillPassRule}
                    onTries={setSkillPassTries}
                  />
                </div>
                {addSkillMutation.isError && (
                  <p className="text-xs text-red-600">Failed to add skill.</p>
                )}
                <div className="flex justify-end gap-2">
                  <Button variant="secondary" size="sm" onClick={() => setShowAddSkill(false)}>
                    Cancel
                  </Button>
                  <Button
                    variant="primary"
                    size="sm"
                    disabled={!skillName.trim() || addSkillMutation.isPending}
                    onClick={() => addSkillMutation.mutate()}
                  >
                    {addSkillMutation.isPending ? "Adding..." : "Add Skill"}
                  </Button>
                </div>
              </div>
            </div>
          )}

          <div className="flex items-center justify-end gap-4 px-4 py-2">
            {deletable && (
              <button
                type="button"
                data-testid="delete-level"
                onClick={() => setConfirmDelete(true)}
                className="text-xs font-medium text-red-600 hover:underline"
              >
                Delete level
              </button>
            )}
            <button
              onClick={() => setShowAddSkill((v) => !v)}
              className="text-xs font-medium text-blue-600 hover:underline dark:text-blue-400"
            >
              {showAddSkill ? "Cancel" : "+ Add Skill"}
            </button>
          </div>
        </div>
      )}
      {/* Stay mounted while open: a 409 refetches usage and must not hide its reason. */}
      {(deletable || confirmDelete) && (
        <DeleteLevelDialog
          pathwayLevel={pathwayLevel}
          open={confirmDelete}
          onClose={() => setConfirmDelete(false)}
          onDeleted={onSkillAdded}
        />
      )}
    </div>
  );
}

const EXTERNAL_SOURCES: ExternalSource[] = [
  "BWF_SHUTTLE_TIME",
  "ACADEMY_CUSTOM",
  "COACH_CREATED",
];

function SkillRow({
  skill,
  externalRefs,
  isBadminton,
  onRefAdded,
  move,
  onRetired,
}: {
  skill: Skill;
  externalRefs: ExternalLessonReference[];
  isBadminton: boolean;
  onRefAdded: () => void;
  move: ReactNode;
  onRetired: (levelUpsQueued: number) => void;
}) {
  const [confirmRetire, setConfirmRetire] = useState(false);
  const retire = useMutation({
    mutationFn: () => retireSkill(skill.skill_id),
    onSuccess: (result) => {
      setConfirmRetire(false);
      onRetired(result.level_ups_queued);
    },
  });
  const [showAddRef, setShowAddRef] = useState(false);
  const [source, setSource] = useState<ExternalSource>(defaultExternalSourceForSport(isBadminton));
  const [sourceTitle, setSourceTitle] = useState("");
  const [moduleName, setModuleName] = useState("");
  const [lessonRange, setLessonRange] = useState("");
  const [referenceTitle, setReferenceTitle] = useState("");
  const [pageHint, setPageHint] = useState("");
  const [internalNote, setInternalNote] = useState("");

  const addRefMutation = useMutation({
    mutationFn: () =>
      addExternalRef(skill.skill_id, {
        source,
        source_title: sourceTitle,
        module_name: moduleName,
        lesson_range: lessonRange,
        reference_title: referenceTitle,
        page_hint: pageHint.trim() || undefined,
        internal_note: internalNote,
      }),
    onSuccess: () => {
      onRefAdded();
      setShowAddRef(false);
      setSourceTitle("");
      setModuleName("");
      setLessonRange("");
      setReferenceTitle("");
      setPageHint("");
      setInternalNote("");
    },
  });

  const passRule = useMutation({
    mutationFn: (body: { pass_rule: SkillPassRule; pass_tries?: number }) =>
      updateSkillPassRule(skill.skill_id, body),
    onSuccess: () => onRefAdded(),
  });
  const rule = skill.pass_rule ?? "ONE_TAP";
  const tries = skill.pass_tries ?? 3;

  const canSubmitRef =
    sourceTitle.trim() && moduleName.trim() && lessonRange.trim() && referenceTitle.trim();

  return (
    <div className="px-4 py-3">
      {/* Wraps on phones so the controls drop below instead of squeezing the text to one word a line. */}
      <div data-testid={`skill-row-${skill.skill_id}`} className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <span className="w-5 text-right text-xs text-neutral-400">{skill.sequence}</span>
        <div className="min-w-0 flex-1 basis-48">
          <span className="text-sm font-medium text-rally-base">{skill.name}</span>
          {skill.description && (
            <span className="mt-0.5 block text-xs text-neutral-400 sm:ml-2 sm:mt-0 sm:inline">
              {skill.description}
            </span>
          )}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {skill.is_required && (
            <span className="rounded-full bg-red-50 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider text-red-600">
              Required
            </span>
          )}
          <span className="rounded-full bg-neutral-100 px-2 py-0.5 text-[10px] font-medium text-neutral-500 dark:bg-neutral-800">
            {skill.scoring_type}
          </span>
          {skill.pass_threshold_pct > 0 && (
            <span className="text-xs text-neutral-400">{skill.pass_threshold_pct}%</span>
          )}
          <PassRuleFields
            rule={rule}
            tries={tries}
            disabled={passRule.isPending}
            onRule={(next) =>
              passRule.mutate({ pass_rule: next, ...(next === "N_TRIES" ? { pass_tries: tries } : {}) })
            }
            onTries={(next) => passRule.mutate({ pass_rule: "N_TRIES", pass_tries: next })}
          />
          {passRule.isError && <span className="text-xs text-red-600">Not saved</span>}
          <button
            onClick={() => setShowAddRef((v) => !v)}
            className="text-xs font-medium text-blue-600 hover:underline dark:text-blue-400"
          >
            {showAddRef ? "Cancel" : "+ Reference"}
          </button>
          {move}
          <button
            type="button"
            onClick={() => setConfirmRetire(true)}
            className="text-xs font-medium text-red-600 hover:underline"
          >
            Retire
          </button>
        </div>
      </div>
      <ConfirmActionDialog
        open={confirmRetire}
        onOpenChange={(next) => {
          setConfirmRetire(next);
          if (!next) retire.reset();
        }}
        overline="Retire skill"
        title={`Retire ${skill.name}?`}
        consequence="The skill leaves the level. Students who were waiting only on it are queued for a level-up."
        confirmLabel="Retire skill"
        pending={retire.isPending}
        error={retire.isError ? retire.error.message || "Could not retire the skill." : null}
        onConfirm={() => retire.mutate()}
      />

      {externalRefs.length > 0 && (
        <ul className="ml-8 mt-2 space-y-1">
          {externalRefs.map((ref) => (
            <li key={ref.ref_id} className="text-xs text-neutral-500">
              <span className="font-medium text-neutral-600 dark:text-neutral-300">
                {ref.reference_title}
              </span>{" "}
              — {ref.source_title} · {ref.module_name} · lessons {ref.lesson_range}
              {ref.page_hint ? ` · ${ref.page_hint}` : ""}
            </li>
          ))}
        </ul>
      )}

      {showAddRef && (
        <div className="ml-8 mt-3 space-y-2 rounded-md bg-neutral-50 p-3 dark:bg-neutral-900">
          <div className="grid gap-2 sm:grid-cols-2">
            <select
              value={source}
              onChange={(e) => setSource(e.target.value as ExternalSource)}
              className="rounded-md border border-neutral-300 px-2 py-1.5 text-xs focus:outline-none"
            >
              {EXTERNAL_SOURCES.map((value) => (
                <option key={value} value={value}>
                  {value}
                </option>
              ))}
            </select>
            <input
              type="text"
              value={sourceTitle}
              onChange={(e) => setSourceTitle(e.target.value)}
              placeholder={sourceTitlePlaceholder(isBadminton)}
              className="rounded-md border border-neutral-300 px-2 py-1.5 text-xs focus:border-blue-500 focus:outline-none"
            />
            <input
              type="text"
              value={moduleName}
              onChange={(e) => setModuleName(e.target.value)}
              placeholder="Module (e.g. Grip and Movement)"
              className="rounded-md border border-neutral-300 px-2 py-1.5 text-xs focus:border-blue-500 focus:outline-none"
            />
            <input
              type="text"
              value={lessonRange}
              onChange={(e) => setLessonRange(e.target.value)}
              placeholder="Lesson range (e.g. 3-4)"
              className="rounded-md border border-neutral-300 px-2 py-1.5 text-xs focus:border-blue-500 focus:outline-none"
            />
            <input
              type="text"
              value={referenceTitle}
              onChange={(e) => setReferenceTitle(e.target.value)}
              placeholder="Reference title"
              className="rounded-md border border-neutral-300 px-2 py-1.5 text-xs focus:border-blue-500 focus:outline-none"
            />
            <input
              type="text"
              value={pageHint}
              onChange={(e) => setPageHint(e.target.value)}
              placeholder="Page hint (optional)"
              className="rounded-md border border-neutral-300 px-2 py-1.5 text-xs focus:border-blue-500 focus:outline-none"
            />
          </div>
          <input
            type="text"
            value={internalNote}
            onChange={(e) => setInternalNote(e.target.value)}
            placeholder="Internal note (why this reference maps to this skill)"
            className="w-full rounded-md border border-neutral-300 px-2 py-1.5 text-xs focus:border-blue-500 focus:outline-none"
          />
          {addRefMutation.isError && (
            <p className="text-xs text-red-600">Failed to add reference.</p>
          )}
          <div className="flex justify-end gap-2">
            <Button variant="secondary" size="sm" onClick={() => setShowAddRef(false)}>
              Cancel
            </Button>
            <Button
              variant="primary"
              size="sm"
              disabled={!canSubmitRef || addRefMutation.isPending}
              onClick={() => addRefMutation.mutate()}
            >
              {addRefMutation.isPending ? "Adding..." : "Add reference"}
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}

function Skeleton() {
  return (
    <div className="space-y-4">
      <div className="h-10 w-64 animate-pulse rounded-lg bg-neutral-100 dark:bg-neutral-800" />
      {[0, 1, 2].map((i) => (
        <div key={i} className="h-32 animate-pulse rounded-lg bg-neutral-100 dark:bg-neutral-800" />
      ))}
    </div>
  );
}

/** The skill's pass rule: one tap, N tries (2 to 10) or a lead coach's tap. */
function PassRuleFields({
  rule,
  tries,
  disabled,
  onRule,
  onTries,
}: {
  rule: SkillPassRule;
  tries: number;
  disabled?: boolean;
  onRule: (rule: SkillPassRule) => void;
  onTries: (tries: number) => void;
}) {
  return (
    <span className="flex items-center gap-1.5">
      <select
        aria-label="How a coach passes this skill"
        value={rule}
        disabled={disabled}
        onChange={(e) => onRule(e.target.value as SkillPassRule)}
        className="rounded-md border border-neutral-300 px-2 py-1 text-sm focus:outline-none"
      >
        {SKILL_PASS_RULES.map((r) => (
          <option key={r.value} value={r.value}>
            {r.label}
          </option>
        ))}
      </select>
      {rule === "N_TRIES" && (
        <select
          aria-label="Tries needed to pass"
          value={tries}
          disabled={disabled}
          onChange={(e) => onTries(Number(e.target.value))}
          className="rounded-md border border-neutral-300 px-2 py-1 text-sm focus:outline-none"
        >
          {Array.from({ length: 9 }, (_, i) => i + 2).map((n) => (
            <option key={n} value={n}>
              {n} tries
            </option>
          ))}
        </select>
      )}
    </span>
  );
}
