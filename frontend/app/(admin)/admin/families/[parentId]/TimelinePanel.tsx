"use client";

import { useInfiniteQuery } from "@tanstack/react-query";

import { Button, Card, Overline, Skeleton } from "@/components/ds";
import { ErrorNotice } from "@/components/ds/error-notice";
import { fetchFamilyTimeline } from "@/lib/api/admin-families";
import { formatInstantDay } from "@/lib/money";
import { queryKeys } from "@/lib/query/keys";

import { timelineEmphasis, timelineKindLabel, timelineTone } from "./family-view";

/**
 * The unified family timeline (People CRM Phase 5): money, enrollment,
 * attendance, requests, messages, coach notes, admin actions and team notes
 * in one newest-first feed, paged by `GET /admin/families/{id}/timeline`.
 * Amounts are already removed server-side for a caller who may not see them.
 */
export function TimelinePanel({ parentId }: { parentId: string }) {
  const timeline = useInfiniteQuery({
    queryKey: queryKeys.admin.familyTimeline(parentId),
    queryFn: ({ pageParam }) => fetchFamilyTimeline(parentId, pageParam),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.next_cursor,
  });

  if (timeline.isLoading) {
    return (
      <Card p={20}>
        <Skeleton lines={6} />
      </Card>
    );
  }
  if (timeline.isError || !timeline.data) {
    return (
      <ErrorNotice
        testId="family-timeline-error"
        message="Could not load this family's timeline."
        onRetry={() => void timeline.refetch()}
        retrying={timeline.isFetching}
      />
    );
  }

  const entries = timeline.data.pages.flatMap((p) => p.entries);
  const warnings = [...new Set(timeline.data.pages.flatMap((p) => p.warnings))];

  return (
    <Card p={20} data-testid="family-timeline">
      <Overline>Timeline</Overline>
      {warnings.length > 0 && (
        <p className="mt-1 text-xs text-rally-muted" data-testid="family-warnings">
          Some history is unavailable right now ({warnings.join(", ")}).
        </p>
      )}
      {entries.length === 0 ? (
        <p className="mt-2 text-sm text-rally-muted">No activity yet.</p>
      ) : (
        <ol className="mt-2 space-y-1.5 border-l-2 border-rally-line pl-3">
          {entries.map((e) => {
            const tone = timelineTone(e);
            return (
              <li
                key={e.entry_id}
                data-testid={`timeline-entry-${e.code}`}
                data-tone={tone}
                data-kind={e.kind}
                className={`text-sm ${tone === "muted" ? "text-rally-muted" : "text-rally-ink"}`}
              >
                <span className="mr-2 font-mono text-xs text-rally-muted">
                  {formatInstantDay(e.at)}
                </span>
                <span className="mr-2 text-xs uppercase tracking-wide text-rally-muted">
                  {timelineKindLabel(e.kind)}
                </span>
                <span className={timelineEmphasis(tone) ? "font-semibold" : ""}>{e.summary}</span>
                {e.detail && (
                  <p className="mt-0.5 whitespace-pre-line break-words text-rally-muted">
                    {e.detail}
                  </p>
                )}
              </li>
            );
          })}
        </ol>
      )}
      {timeline.hasNextPage && (
        <Button
          size="sm"
          variant="secondary"
          className="mt-3"
          data-testid="family-timeline-older"
          disabled={timeline.isFetchingNextPage}
          onClick={() => void timeline.fetchNextPage()}
        >
          {timeline.isFetchingNextPage ? "Loading…" : "Show older"}
        </Button>
      )}
    </Card>
  );
}
