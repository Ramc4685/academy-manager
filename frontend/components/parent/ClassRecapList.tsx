"use client";

import { useInfiniteQuery, useQuery } from "@tanstack/react-query";

import { Button } from "@/components/ds/button";
import {
  listChildClassRecaps,
  type ChildClassRecap,
  type ChildRecapSkill,
} from "@/lib/api/class-recap";
import { getParentAcademy } from "@/lib/api/parent";
import { formatInAcademyZone, resolveAcademyTimeZone } from "@/lib/format/academy-time";
import { queryKeys } from "@/lib/query/keys";

const names = (skills: ChildRecapSkill[]) => skills.map((s) => s.name).join(", ");

export function ClassRecapItems({
  recaps,
  firstName,
  timeZone,
}: {
  recaps: ChildClassRecap[];
  firstName: string;
  timeZone: string | null;
}) {
  const zone = resolveAcademyTimeZone(timeZone).timeZone;
  return (
    <ol className="mt-2 divide-y divide-rally-line">
      {recaps.map((r) => (
        <li key={r.occurrence_id} className="py-3 text-sm" data-testid="parent-class-recap-item">
          <p className="text-xs font-semibold text-rally-muted">
            {formatInAcademyZone(r.class_starts_at, zone, {
              weekday: "short",
              month: "short",
              day: "numeric",
              year: "numeric",
            })}
          </p>
          {r.earned_skills.length > 0 && (
            <p
              className="mt-1 font-semibold text-rally-ink"
              data-testid="parent-class-recap-earned"
            >
              {`🏅 Passed at this class: ${names(r.earned_skills)}`}
            </p>
          )}
          <p className="mt-1 text-rally-ink">{`Class lesson: ${names(r.taught_skills)}`}</p>
          {/* S18: no negative line; an empty list just says nothing. */}
          {r.practiced_skills.length > 0 && (
            <p className="text-rally-ink">{`${firstName} practised: ${names(r.practiced_skills)}`}</p>
          )}
        </li>
      ))}
    </ol>
  );
}

/**
 * The child's own classes, newest first, a page at a time. A pass shows on
 * the class that earned it; current level progress is shown separately.
 * The parent's own child only: no report text, no other children.
 */
export function ClassRecapList({ studentId, firstName }: { studentId: string; firstName: string }) {
  const timeline = useInfiniteQuery({
    queryKey: queryKeys.parent.classRecaps(studentId),
    queryFn: ({ pageParam }) => listChildClassRecaps(studentId, pageParam),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.next_cursor,
  });
  const { data: academy } = useQuery({
    queryKey: queryKeys.parent.academy(),
    queryFn: getParentAcademy,
  });
  const recaps = timeline.data?.pages.flatMap((p) => p.recaps) ?? [];
  if (recaps.length === 0) return null;
  return (
    <section
      className="rounded-2xl border border-rally-line bg-white p-4"
      data-testid="parent-class-recaps"
      aria-labelledby="parent-class-recaps-title"
    >
      <h2 id="parent-class-recaps-title" className="text-sm font-bold text-rally-ink">
        {`${firstName}'s classes`}
      </h2>
      <ClassRecapItems
        recaps={recaps}
        firstName={firstName}
        timeZone={academy?.timezone ?? null}
      />
      {timeline.hasNextPage && (
        <Button
          variant="secondary"
          size="sm"
          className="mt-2"
          data-testid="parent-class-recaps-more"
          disabled={timeline.isFetchingNextPage}
          onClick={() => void timeline.fetchNextPage()}
        >
          {timeline.isFetchingNextPage ? "Loading…" : "Show older classes"}
        </Button>
      )}
    </section>
  );
}
