"use client";

import { useState } from "react";
import { useParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  createLevel,
  createSkill,
  getFullPathway,
  listLessonCards,
  seedLessonCards,
  type PathwayLevel,
  type SeedLessonCardsResult,
  type Skill,
} from "@/lib/api/curriculum";
import { Card } from "@/components/ds/card";
import { Button } from "@/components/ds/button";
import { queryKeys } from "@/lib/query/keys";

export default function AdminPathwayDetailPage() {
  const { programId } = useParams<{ programId: string }>();
  const queryClient = useQueryClient();

  const { data, isLoading, isError } = useQuery({
    queryKey: ["admin", "pathway", programId],
    queryFn: () => getFullPathway(programId),
    enabled: Boolean(programId),
  });

  const [showAddLevel, setShowAddLevel] = useState(false);
  const [levelName, setLevelName] = useState("");
  const [levelDescription, setLevelDescription] = useState("");

  const addLevelMutation = useMutation({
    mutationFn: () =>
      createLevel(programId, {
        name: levelName,
        description: levelDescription,
        sequence: (data?.levels.length ?? 0) + 1,
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
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold">{data.program.name}</h1>
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
          {data.levels.map((pathwayLevel) => (
            <LevelAccordion
              key={pathwayLevel.level.level_id}
              pathwayLevel={pathwayLevel}
              onSkillAdded={() =>
                void queryClient.invalidateQueries({ queryKey: ["admin", "pathway", programId] })
              }
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

function LevelAccordion({
  pathwayLevel,
  onSkillAdded,
}: {
  pathwayLevel: PathwayLevel;
  onSkillAdded: () => void;
}) {
  const [open, setOpen] = useState(true);
  const [showAddSkill, setShowAddSkill] = useState(false);
  const [skillName, setSkillName] = useState("");
  const [skillDescription, setSkillDescription] = useState("");
  const [skillRequired, setSkillRequired] = useState(true);
  const [skillScoringType, setSkillScoringType] = useState("binary");

  const addSkillMutation = useMutation({
    mutationFn: () =>
      createSkill(pathwayLevel.level.level_id, {
        name: skillName,
        description: skillDescription,
        is_required: skillRequired,
        scoring_type: skillScoringType,
      }),
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
          <span className="flex h-6 w-6 items-center justify-center rounded-full bg-blue-600 text-[11px] font-bold text-white">
            {level.sequence}
          </span>
          <div>
            <span className="font-semibold text-rally-base">{level.name}</span>
            {level.description && (
              <span className="ml-2 text-sm text-neutral-500">{level.description}</span>
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
          {skills.length === 0 && !showAddSkill && (
            <p className="px-4 py-3 text-sm text-neutral-400">No skills yet.</p>
          )}

          {skills.map(({ skill }) => (
            <SkillRow key={skill.skill_id} skill={skill} />
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
                    />
                    Required
                  </label>
                  <select
                    value={skillScoringType}
                    onChange={(e) => setSkillScoringType(e.target.value)}
                    className="rounded-md border border-neutral-300 px-2 py-1 text-sm focus:outline-none"
                  >
                    <option value="binary">Binary (pass/fail)</option>
                    <option value="percentage">Percentage</option>
                    <option value="count">Count</option>
                  </select>
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

          <div className="flex justify-end px-4 py-2">
            <button
              onClick={() => setShowAddSkill((v) => !v)}
              className="text-xs font-medium text-blue-600 hover:underline dark:text-blue-400"
            >
              {showAddSkill ? "Cancel" : "+ Add Skill"}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

function SkillRow({ skill }: { skill: Skill }) {
  return (
    <div className="flex items-center gap-3 px-4 py-3">
      <span className="w-5 text-right text-xs text-neutral-400">{skill.sequence}</span>
      <div className="min-w-0 flex-1">
        <span className="text-sm font-medium text-rally-base">{skill.name}</span>
        {skill.description && (
          <span className="ml-2 text-xs text-neutral-400">{skill.description}</span>
        )}
      </div>
      <div className="flex shrink-0 items-center gap-2">
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
      </div>
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
