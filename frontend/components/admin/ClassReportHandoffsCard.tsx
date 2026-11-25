"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { ClassRecapPanel } from "@/components/coach/ClassRecapPanel";
import { Button } from "@/components/ds/button";
import { RallyModal } from "@/components/ds/dialog-chrome";
import { useAcademyTimezone } from "@/components/admin/use-academy-today";
import { listClassReportHandoffs, type ClassReportHandoff } from "@/lib/api/class-recap";
import { parseAcademyInstant, resolveAcademyTimeZone } from "@/lib/format/academy-time";
import { queryKeys } from "@/lib/query/keys";

/** Any class date's recap, opened from the admin side (session page or this card). */
export function ClassRecapDialog({
  occurrenceId,
  when,
  onClose,
}: {
  occurrenceId: string | null;
  when: string;
  onClose: () => void;
}) {
  return (
    <RallyModal
      open={Boolean(occurrenceId)}
      onOpenChange={(next) => {
        if (!next) onClose();
      }}
      title="Class recap"
      description={when}
      overline="Class date"
    >
      {occurrenceId && <ClassRecapPanel occurrenceId={occurrenceId} />}
    </RallyModal>
  );
}

function classWhen(iso: string, timeZone: string | null): string {
  return parseAcademyInstant(iso).toLocaleString("en-US", {
    weekday: "short",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
    timeZone: resolveAcademyTimeZone(timeZone).timeZone,
  });
}

export function ClassReportHandoffList({
  reports,
  timeZone,
  onOpen,
}: {
  reports: ClassReportHandoff[];
  timeZone: string | null;
  onOpen: (report: ClassReportHandoff) => void;
}) {
  if (reports.length === 0) {
    return (
      <p className="text-sm text-rally-subtle">
        No reports waiting. Open any class date&apos;s recap from its class page.
      </p>
    );
  }
  return (
    <ul className="divide-y divide-rally-line" data-testid="class-report-handoffs">
      {reports.map((r) => (
        <li key={r.report_id} className="flex items-start gap-3 py-2">
          <div className="min-w-0 flex-1">
            <p className="text-xs text-rally-muted">{classWhen(r.class_starts_at, timeZone)}</p>
            <p className="line-clamp-2 text-sm text-rally-ink">{r.text}</p>
          </div>
          <Button variant="secondary" size="sm" onClick={() => onOpen(r)}>
            Open recap
          </Button>
        </li>
      ))}
    </ul>
  );
}

/** Owner-only: after-class reports a coach sent for hand entry. */
export function ClassReportHandoffsCard() {
  const [open, setOpen] = useState<ClassReportHandoff | null>(null);
  const timeZone = useAcademyTimezone();
  const query = useQuery({
    queryKey: queryKeys.classRecap.handoffs(),
    queryFn: listClassReportHandoffs,
  });
  if (query.isLoading || query.isError) return null;
  return (
    <section className="rounded-2xl border border-rally-line bg-white p-4">
      <h2 className="text-sm font-bold text-rally-ink">After-class reports for you</h2>
      <div className="mt-2">
        <ClassReportHandoffList
          reports={query.data?.reports ?? []}
          timeZone={timeZone}
          onOpen={setOpen}
        />
      </div>
      <ClassRecapDialog
        occurrenceId={open?.occurrence_id ?? null}
        when={open ? classWhen(open.class_starts_at, timeZone) : ""}
        onClose={() => {
          setOpen(null);
          void query.refetch();
        }}
      />
    </section>
  );
}
