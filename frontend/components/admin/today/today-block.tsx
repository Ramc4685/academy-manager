"use client";

/**
 * S64: the Today block that leads the admin dashboard: the academy date,
 * the quick actions (S65), today's classes and the roster sheet. `/admin?class=<occurrence_id>` opens
 * a class's roster; closing it drops the param.
 */

import type { ReactNode } from "react";
import type { Route } from "next";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";

import { getAdminToday } from "@/lib/api/admin";
import { academyDateISO } from "@/lib/format/academy-time";
import { queryKeys } from "@/lib/query/keys";
import { useAcademyTimezone } from "@/components/admin/use-academy-today";
import { Card } from "@/components/ds/card";
import { Overline } from "@/components/ds/typography";

import { normalizeToday, todayDateLabel } from "./format";
import { QuickActions } from "./quick-actions";
import { RosterSheet } from "./roster-sheet";
import { LiveHealthCount, TodayClassesView } from "./today-classes";

export function TodayHeader({ date, actions }: { date: string; actions?: ReactNode }) {
  return (
    <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
      <Overline>Today · {todayDateLabel(date)}</Overline>
      {actions}
    </div>
  );
}

export function TodayBlock() {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const academyTimezone = useAcademyTimezone();
  const todayQuery = useQuery({
    queryKey: queryKeys.admin.today(),
    queryFn: () => getAdminToday(),
    refetchInterval: 60_000,
  });
  const fallbackDate = academyDateISO(academyTimezone);
  const data = normalizeToday(todayQuery.data, fallbackDate);
  const openId = params.get("class");
  const openClass = data?.classes.find((cls) => cls.occurrence_id === openId) ?? null;

  function setOpen(occurrenceId: string | null) {
    const next = new URLSearchParams(params.toString());
    if (occurrenceId) next.set("class", occurrenceId);
    else next.delete("class");
    const qs = next.toString();
    router.replace((qs ? `${pathname}?${qs}` : pathname) as Route, { scroll: false });
  }

  return (
    <Card p={20} data-testid="admin-today">
      {/* Quick actions render at once and keep working if the classes fail to load. */}
      <TodayHeader date={data?.date ?? fallbackDate} actions={<QuickActions today={data} />} />
      <TodayClassesView
        data={data}
        isLoading={todayQuery.isLoading}
        isError={todayQuery.isError}
        retrying={todayQuery.isFetching}
        onRetry={() => void todayQuery.refetch()}
        healthEnabled={data?.health_enabled ?? false}
        onOpen={(id) => {
          setOpen(id);
          void todayQuery.refetch();
        }}
        renderHealth={(cls) => <LiveHealthCount occurrenceId={cls.occurrence_id} />}
      />
      {data && openClass ? (
        <RosterSheet
          cls={openClass}
          date={data.date}
          timezone={data.timezone}
          healthEnabled={data.health_enabled}
          onClose={() => setOpen(null)}
        />
      ) : null}
    </Card>
  );
}
