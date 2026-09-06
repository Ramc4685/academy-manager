"use client";

import { useState } from "react";

import { Button, Card, Overline } from "@/components/ds";
import type { FamilyTimelineEntry } from "@/lib/api/admin-families";
import { formatInstantDay } from "@/lib/money";

import { timelineTone } from "./family-view";

const PAGE = 50;

export function TimelinePanel({
  timeline,
  warnings,
}: {
  timeline: FamilyTimelineEntry[];
  warnings: string[];
}) {
  const [shown, setShown] = useState(PAGE);
  return (
    <Card p={20} data-testid="family-timeline">
      <Overline>Timeline</Overline>
      {warnings.length > 0 && (
        <p className="mt-1 text-xs text-rally-muted" data-testid="family-warnings">
          Some history is unavailable right now ({warnings.join(", ")}).
        </p>
      )}
      {timeline.length === 0 ? (
        <p className="mt-2 text-sm text-rally-muted">No activity yet.</p>
      ) : (
        <ol className="mt-2 space-y-1 border-l-2 border-rally-line pl-3">
          {timeline.slice(0, shown).map((e, i) => {
            const tone = timelineTone(e);
            return (
              <li
                key={`${e.code}-${e.at}-${i}`}
                data-testid={`timeline-entry-${e.code}`}
                data-tone={tone}
                className={`text-sm ${tone === "muted" ? "text-rally-muted" : "text-rally-ink"}`}
              >
                <span className="mr-2 font-mono text-xs text-rally-muted">
                  {formatInstantDay(e.at)}
                </span>
                <span className={tone === "money" || tone === "admin" ? "font-semibold" : ""}>
                  {e.summary}
                </span>
              </li>
            );
          })}
        </ol>
      )}
      {timeline.length > shown && (
        <Button
          size="sm"
          variant="secondary"
          className="mt-3"
          onClick={() => setShown((n) => n + PAGE)}
        >
          Show older
        </Button>
      )}
    </Card>
  );
}
