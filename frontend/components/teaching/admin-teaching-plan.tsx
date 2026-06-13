"use client";

import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ExternalLink } from "lucide-react";

import { listSessionOccurrences, type AdminSessionOccurrenceView } from "@/lib/api/admin";
import { getAdminOccurrenceTeachingPlan } from "@/lib/api/admin-teaching";
import { queryKeys } from "@/lib/query/keys";
import { formatSessionTimeRange } from "@/lib/time/session-time";
import type { LevelTeachingGroup } from "@/components/teaching/types";
import { LessonCardView } from "@/components/teaching/lesson-card";
import { StudentFocusReadOnlyRow } from "@/components/teaching/student-focus-row";

export function AdminTeachingPlan({
  sessionId,
  programId,
}: {
  sessionId: string;
  programId?: string | null;
}) {
  const [occurrenceId, setOccurrenceId] = useState("");
  const occurrencesQuery = useQuery({
    queryKey: queryKeys.admin.sessionOccurrences(sessionId),
    queryFn: () => listSessionOccurrences(sessionId),
  });
  const occurrences = useMemo(
    () => occurrencesQuery.data?.occurrences ?? [],
    [occurrencesQuery.data?.occurrences],
  );

  useEffect(() => {
    if (!occurrenceId && occurrences.length > 0) {
      setOccurrenceId(occurrences[0].occurrence_id);
    }
  }, [occurrenceId, occurrences]);

  const selectedOccurrence = useMemo(
    () => occurrences.find((occurrence) => occurrence.occurrence_id === occurrenceId) ?? null,
    [occurrenceId, occurrences],
  );

  const planQuery = useQuery({
    queryKey: queryKeys.admin.teachingPlan(occurrenceId, programId),
    queryFn: () => getAdminOccurrenceTeachingPlan(occurrenceId, programId),
    enabled: Boolean(occurrenceId),
    staleTime: 5 * 60 * 1000,
  });

  if (occurrencesQuery.isLoading) return <PlanSkeleton />;

  if (occurrencesQuery.isError) {
    return (
      <p role="alert" className="rounded-md bg-red-50 p-3 text-sm text-red-700">
        Could not load session occurrences.
      </p>
    );
  }

  if (occurrences.length === 0) {
    return (
      <p className="text-sm text-rally-subtle" data-testid="admin-teaching-plan-empty">
        No dated occurrences are available for this session.
      </p>
    );
  }

  return (
    <section data-testid="admin-teaching-plan" className="space-y-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <label className="grid gap-1 text-sm font-medium text-rally-ink">
          Occurrence
          <select
            value={occurrenceId}
            onChange={(event) => setOccurrenceId(event.target.value)}
            className="min-h-10 rounded-md border border-rally-line bg-white px-3 text-sm text-rally-ink focus:outline-none focus:ring-2 focus:ring-rally-cobalt-600/25"
          >
            {occurrences.map((occurrence) => (
              <option key={occurrence.occurrence_id} value={occurrence.occurrence_id}>
                {occurrenceLabel(occurrence)}
              </option>
            ))}
          </select>
        </label>
        {selectedOccurrence && (
          <p className="text-sm text-rally-muted">
            Coach{" "}
            {selectedOccurrence.actual_coach_id ??
              selectedOccurrence.substitute_coach_id ??
              selectedOccurrence.scheduled_coach_id}
          </p>
        )}
      </div>

      {planQuery.isLoading && <PlanSkeleton />}

      {planQuery.isError && (
        <div
          role="alert"
          className="rounded-md border border-red-200 bg-red-50 p-4 text-sm text-red-800"
        >
          <p>Could not load the teaching plan for this occurrence.</p>
          <button
            type="button"
            onClick={() => void planQuery.refetch()}
            className="mt-2 min-h-9 rounded-md border border-red-200 bg-white px-3 font-semibold"
          >
            Retry
          </button>
        </div>
      )}

      {planQuery.data && !planQuery.data.pathway_configured && (
        <p className="rounded-md border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800">
          No skill pathway is configured for this program yet.
        </p>
      )}

      {planQuery.data && (
        <div className="space-y-4">
          {planQuery.data.groups.length === 0 && planQuery.data.unplaced.length === 0 && (
            <p className="text-sm text-rally-subtle">No students on this roster.</p>
          )}

          {planQuery.data.groups.map((group) => (
            <LevelSection key={group.level_id} group={group} />
          ))}

          {planQuery.data.unplaced.length > 0 && (
            <div className="rounded-md border border-dashed border-rally-line p-4">
              <p className="mb-2 text-sm font-semibold text-rally-muted">
                Not placed in a level
              </p>
              <ul className="space-y-1 text-sm text-rally-muted">
                {planQuery.data.unplaced.map((student) => (
                  <li key={student.student_id}>{student.student_name}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </section>
  );
}

function LevelSection({ group }: { group: LevelTeachingGroup }) {
  return (
    <section data-testid={`admin-plan-level-${group.level_sequence}`} className="space-y-3">
      <h3 className="text-sm font-semibold text-rally-base">
        Level {group.level_sequence} · {group.level_name}
      </h3>

      {group.lesson_card ? (
        <LessonCardView card={group.lesson_card} levelYoutubeLinks={group.youtube_links} />
      ) : (
        group.youtube_links.length > 0 && (
          <div className="flex flex-wrap gap-2">
            {group.youtube_links.map((link, index) => (
              <a
                key={link.url}
                href={link.url}
                target="_blank"
                rel="noopener noreferrer"
                data-testid={`admin-plan-level-youtube-${group.level_sequence}-${index}`}
                className="inline-flex min-h-touch items-center gap-1.5 rounded-lg border border-red-200 bg-red-50 px-3 text-xs font-medium text-red-700 hover:bg-red-100"
              >
                <ExternalLink className="size-3.5" aria-hidden="true" />
                {link.title || "Watch video"}
              </a>
            ))}
          </div>
        )
      )}

      {group.students.length > 0 && (
        <ul className="space-y-2">
          {group.students.map((student) => (
            <StudentFocusReadOnlyRow key={student.student_id} student={student} />
          ))}
        </ul>
      )}
    </section>
  );
}

function occurrenceLabel(occurrence: AdminSessionOccurrenceView): string {
  const date = new Date(occurrence.start_at).toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
  });
  return `${date} · ${formatSessionTimeRange(occurrence.start_at, occurrence.end_at)}`;
}

function PlanSkeleton() {
  return (
    <div className="space-y-3">
      {[0, 1].map((index) => (
        <div
          key={index}
          className="h-32 animate-pulse rounded-md border border-rally-line bg-rally-paper"
        />
      ))}
    </div>
  );
}
