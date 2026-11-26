"use client";

/**
 * S68 "What we teach": the academy's levels, skills and lesson plans as
 * reference reading (docs/design/coach-home.md 3.4). Not private, so the
 * coach persister may keep it for offline reading.
 */

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { EmptyState, ErrorNotice, Skeleton } from "@/components/ds";
import { markWelcome } from "@/components/coach/welcome-card";
import { getCoachPathway, getCoachProfile, type CoachPathway } from "@/lib/api/coach";
import { queryKeys } from "@/lib/query/keys";

type Level = CoachPathway["programs"][number]["levels"][number];

function Facts({ title, items }: { title: string; items: string[] }) {
  if (items.length === 0) return null;
  return (
    <div className="mt-2">
      <h4 className="text-sm font-semibold">{title}</h4>
      <ul className="list-disc pl-5 text-sm">
        {items.map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
    </div>
  );
}

function LevelPanel({ level, open }: { level: Level; open: boolean }) {
  return (
    <details open={open} className="rounded-lg border border-rally-line bg-white dark:bg-neutral-900">
      <summary className="flex min-h-touch cursor-pointer items-center px-4 py-2">
        <span>
          <span className="block text-xs font-semibold uppercase tracking-wide text-neutral-500">
            Level {level.sequence}
          </span>
          <span className="block font-semibold">{level.name}</span>
        </span>
      </summary>
      <div className="px-4 pb-4">
        {level.description && <p className="text-sm text-neutral-600 dark:text-neutral-300">{level.description}</p>}
        {level.skills.length > 0 && (
          <>
            <h3 className="mt-3 text-xs font-semibold uppercase tracking-wide text-neutral-500">Skills</h3>
            <p className="text-sm">{level.skills.map((s) => s.name).join(" · ")}</p>
          </>
        )}
        <h3 className="mt-3 text-xs font-semibold uppercase tracking-wide text-neutral-500">Lessons</h3>
        {level.lessons.length === 0 ? (
          <p className="text-sm text-neutral-600 dark:text-neutral-300">No lesson plans for this level yet.</p>
        ) : (
          <ul className="mt-1 space-y-1">
            {level.lessons.map((lesson) => (
              <li key={lesson.card_id}>
                <details>
                  <summary className="flex min-h-touch cursor-pointer items-center text-sm font-medium">
                    {lesson.lesson_number} · {lesson.title}
                  </summary>
                  <div className="pb-2 pl-4 text-sm">
                    {lesson.goal_summary && <p>Goal: {lesson.goal_summary}</p>}
                    <Facts title="Teaching points" items={lesson.teaching_points} />
                    {lesson.equipment.length > 0 && <p className="mt-2">Equipment: {lesson.equipment.join(", ")}</p>}
                    {lesson.safety_notes.length > 0 && <p className="mt-1">Safety: {lesson.safety_notes.join(", ")}</p>}
                    {lesson.activity_summary && <p className="mt-1">Activity: {lesson.activity_summary}</p>}
                    {lesson.video_url && (
                      <a
                        href={lesson.video_url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="mt-1 inline-flex min-h-touch items-center text-rally-cobalt-700 underline"
                      >
                        Watch the drill
                      </a>
                    )}
                  </div>
                </details>
              </li>
            ))}
          </ul>
        )}
      </div>
    </details>
  );
}

export default function CoachPathwayPage() {
  const router = useRouter();
  const pathway = useQuery({ queryKey: queryKeys.coach.pathway(), queryFn: getCoachPathway });
  const { data: profile } = useQuery({ queryKey: queryKeys.coach.profile(), queryFn: getCoachProfile });
  const [programIndex, setProgramIndex] = useState(0);

  useEffect(() => markWelcome(profile?.user_id, { pathway: true }), [profile?.user_id]);

  const programs = pathway.data?.programs ?? [];
  const program = programs[programIndex] ?? programs[0];

  return (
    <section data-testid="coach-pathway" className="mx-auto max-w-xl">
      <button
        type="button"
        onClick={() => router.back()}
        className="inline-flex min-h-touch items-center text-sm text-rally-cobalt-700 hover:underline"
      >
        ← Back
      </button>
      <h1 className="mb-2 text-2xl font-semibold">What we teach</h1>

      {pathway.isPending && (
        <div className="space-y-2">
          <Skeleton variant="block" height={64} />
          <Skeleton variant="block" height={64} />
        </div>
      )}

      {pathway.isError && (
        <ErrorNotice
          message="We could not load the levels."
          onRetry={() => void pathway.refetch()}
          retrying={pathway.isFetching}
        />
      )}

      {pathway.isSuccess && (!program || program.levels.length === 0) && (
        <EmptyState
          title="The academy has not set up its levels yet."
          description="Ask the owner what to teach, or use the plan on your class."
        />
      )}

      {program && program.levels.length > 0 && (
        <>
          {programs.length > 1 && (
            <label className="mb-2 block text-sm">
              <span className="sr-only">Program</span>
              <select
                value={programIndex}
                onChange={(e) => setProgramIndex(Number(e.target.value))}
                className="min-h-touch w-full rounded-md border border-neutral-300 bg-white px-3 dark:border-neutral-700 dark:bg-neutral-900"
              >
                {programs.map((p, i) => (
                  <option key={p.program_id} value={i}>
                    {p.name}
                  </option>
                ))}
              </select>
            </label>
          )}
          <p className="text-sm font-medium">
            {program.name} · {program.levels.length} {program.levels.length === 1 ? "level" : "levels"}
          </p>
          <p className="mb-3 text-sm text-neutral-600 dark:text-neutral-300">
            Children move up a level when they pass that level&apos;s skills. You record passes on the class&apos;s
            Skills tab.
          </p>
          <div className="space-y-2" data-testid="pathway-levels">
            {program.levels.map((level, i) => (
              <LevelPanel key={level.level_id} level={level} open={i === 0} />
            ))}
          </div>
        </>
      )}
    </section>
  );
}
