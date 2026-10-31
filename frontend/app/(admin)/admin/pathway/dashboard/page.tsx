"use client";

import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  getAdminPathwayDashboard,
  setLevelUpRule,
  type PathwayDashboard,
} from "@/lib/api/curriculum";
import { queryKeys } from "@/lib/query/keys";
import { Card } from "@/components/ds/card";
import { ErrorNotice } from "@/components/ds/error-notice";
import { Skeleton } from "@/components/ds/skeleton";

const progressOverviewEnabled = process.env.NEXT_PUBLIC_SKILL_PROGRESS_OVERVIEW === "1";

export default function AdminPathwayDashboardPage() {
  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: queryKeys.admin.pathwayDashboard(),
    queryFn: getAdminPathwayDashboard,
    staleTime: 2 * 60 * 1000,
  });

  return (
    <section data-testid="admin-pathway-dashboard" className="space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="text-xs font-bold uppercase tracking-wider text-rally-cobalt-700">
            Skill pathway{data ? ` · ${data.program_name}` : ""}
          </p>
          <h1 className="font-display text-3xl font-bold text-rally-ink">
            Who is moving, who is stuck
          </h1>
        </div>
        {progressOverviewEnabled && (
          <Link
            href="/admin/pathway/progress"
            className="text-sm font-semibold text-rally-cobalt-700 hover:text-rally-cobalt-900"
          >
            All students →
          </Link>
        )}
      </div>

      {isError ? (
        <ErrorNotice message="Could not load the skill pathway." onRetry={() => refetch()} />
      ) : isLoading || !data ? (
        <div className="grid gap-3 md:grid-cols-4" data-testid="pathway-dashboard-loading">
          {[0, 1, 2, 3].map((i) => (
            <Skeleton key={i} variant="block" height={96} />
          ))}
        </div>
      ) : (
        <Dashboard data={data} />
      )}
    </section>
  );
}

function Dashboard({ data }: { data: PathwayDashboard }) {
  const maxPlayers = Math.max(1, ...data.levels.map((l) => l.player_count));
  return (
    <>
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Kpi label="Skills mastered this week" value={data.skills_mastered_this_week} />
        <Kpi label="Level-ups this month" value={data.level_ups_this_month} />
        <Kpi label="One skill from levelling up" value={data.almost_there.length} tone="cobalt" />
        <Kpi label="No new skill in 6 weeks" value={data.stuck.length} tone="amber" />
      </div>

      <div className="grid gap-4 lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
        <Card p={20}>
          <h2 className="font-display text-lg font-bold text-rally-ink">Players by level</h2>
          <ul className="mt-3 space-y-3">
            {data.levels.map((level) => (
              <li
                key={level.level_id}
                className="grid grid-cols-[minmax(0,10rem)_1fr_2rem] items-center gap-3"
              >
                <span className="truncate text-sm font-semibold text-rally-ink">
                  {level.sequence} · {level.name}
                </span>
                <span className="block h-3.5 overflow-hidden rounded-full bg-status-slate-100">
                  <span
                    className="block h-full rounded-full bg-rally-cobalt-600"
                    style={{ width: `${Math.round((level.player_count / maxPlayers) * 100)}%` }}
                  />
                </span>
                <span className="text-right text-sm font-bold text-rally-ink">
                  {level.player_count}
                </span>
              </li>
            ))}
          </ul>
          <p className="mt-3 text-xs text-rally-muted">
            Use this to plan classes: when a level fills up, open a new group.
            {data.unplaced_count > 0 && ` ${data.unplaced_count} active students are not placed yet.`}
          </p>
        </Card>
        <LevelUpRuleCard data={data} />
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <ListCard
          title="Almost there"
          blurb="One skill left. Good moment to tell the parent what comes next."
          empty="Nobody is one skill away right now."
          testId="pathway-almost-there"
          rows={data.almost_there.map((a) => ({
            id: a.student_id,
            name: a.student_name,
            detail: `Level ${a.level_sequence} · needs ${a.missing_skill_name}`,
            href: `/admin/students/${encodeURIComponent(a.student_id)}`,
            action: "Contact family",
          }))}
        />
        <ListCard
          title="Stuck"
          blurb="No new skill in 6+ weeks. Parents of these kids are the ones who quietly leave."
          empty="Nobody is stuck. Every placed student has a recent win."
          testId="pathway-stuck"
          tone="amber"
          rows={data.stuck.map((s) => ({
            id: s.student_id,
            name: s.student_name,
            detail: `Level ${s.level_sequence} · ${s.skills_passed} of ${s.skills_total} skills · ${
              s.last_win_at ? `last win ${weeksAgo(s.last_win_at)}` : "no win yet"
            }`,
            href: `/admin/students/${encodeURIComponent(s.student_id)}`,
            action: "Offer a 1-on-1",
          }))}
        />
        <Card p={20} data-testid="pathway-coaches">
          <h2 className="font-display text-lg font-bold text-rally-ink">Coaches logging</h2>
          <p className="mt-1 text-sm text-rally-muted">Skills ticked in class this week.</p>
          {data.coaches.length === 0 ? (
            <p className="mt-3 text-sm text-rally-muted">No coaches yet.</p>
          ) : (
            <ul className="mt-2">
              {data.coaches.map((c) => (
                <li
                  key={c.coach_id}
                  className="flex items-center justify-between gap-2 border-t border-status-slate-100 py-2.5"
                >
                  <span className="text-sm font-bold text-rally-ink">{c.coach_name}</span>
                  <span
                    className={`rounded-full px-2.5 py-1 text-xs font-bold ${
                      c.skills_ticked > 0
                        ? "bg-status-green-50 text-status-green-800"
                        : "bg-status-red-50 text-status-red-800"
                    }`}
                  >
                    {c.skills_ticked}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>
    </>
  );
}

function Kpi({
  label,
  value,
  tone,
}: {
  label: string;
  value: number;
  tone?: "cobalt" | "amber";
}) {
  const box =
    tone === "amber"
      ? "border-status-amber-500 bg-status-amber-50"
      : "border-rally-line bg-white";
  const text =
    tone === "amber"
      ? "text-status-amber-800"
      : tone === "cobalt"
        ? "text-rally-cobalt-700"
        : "text-rally-ink";
  return (
    <div className={`flex flex-col gap-1 rounded-xl border p-4 ${box}`}>
      <span className={`text-sm ${tone === "amber" ? text : "text-status-slate-600"}`}>
        {label}
      </span>
      <span className={`font-display text-3xl font-bold ${text}`}>{value}</span>
    </div>
  );
}

function LevelUpRuleCard({ data }: { data: PathwayDashboard }) {
  const queryClient = useQueryClient();
  const mutation = useMutation({
    mutationFn: (approveFirst: boolean) =>
      setLevelUpRule(
        data.levels.map((l) => l.level_id),
        approveFirst,
      ),
    onSettled: () =>
      queryClient.invalidateQueries({ queryKey: queryKeys.admin.pathwayDashboard() }),
  });
  // Show the pick while it saves; the refetch confirms it.
  const rule = mutation.isPending
    ? mutation.variables
      ? "approve_first"
      : "automatic"
    : data.level_up_rule;
  const options = [
    {
      value: "automatic",
      title: "Automatic",
      body: "Last skill ticked = moved up in the evening. I get a note and can undo.",
    },
    {
      value: "approve_first",
      title: "I approve first",
      body: "Level-ups wait for one tap from my Today screen.",
    },
  ] as const;
  return (
    <Card p={20} data-testid="pathway-level-up-rule">
      <fieldset disabled={mutation.isPending || data.levels.length === 0}>
        <legend className="font-display text-lg font-bold text-rally-ink">Level-up rule</legend>
        {rule === "mixed" && (
          <p className="mt-1 text-sm text-status-amber-800">
            Levels are set differently today. Picking one applies it to every level.
          </p>
        )}
        <div className="mt-3 space-y-2">
          {options.map((o) => {
            const checked = rule === o.value;
            return (
              <label
                key={o.value}
                className={`flex cursor-pointer items-start gap-3 rounded-xl border-2 p-3 text-sm ${
                  checked ? "border-rally-cobalt-600 bg-rally-cobalt-50" : "border-rally-line"
                }`}
              >
                <input
                  type="radio"
                  name="level-up-rule"
                  className="mt-0.5 h-4 w-4"
                  checked={checked}
                  onChange={() => mutation.mutate(o.value === "approve_first")}
                />
                <span className="flex flex-col gap-0.5">
                  <b className="text-rally-ink">{o.title}</b>
                  <span className="text-status-slate-700">{o.body}</span>
                </span>
              </label>
            );
          })}
        </div>
        {mutation.isError && (
          <p role="alert" className="mt-2 text-sm text-status-red-800">
            Could not save the rule. Some levels may not have changed; try again.
          </p>
        )}
      </fieldset>
    </Card>
  );
}

function ListCard({
  title,
  blurb,
  empty,
  rows,
  testId,
  tone,
}: {
  title: string;
  blurb: string;
  empty: string;
  testId: string;
  tone?: "amber";
  rows: { id: string; name: string; detail: string; href: string; action: string }[];
}) {
  return (
    <Card
      p={20}
      data-testid={testId}
      className={tone === "amber" ? "!border-status-amber-500" : ""}
    >
      <h2 className="font-display text-lg font-bold text-rally-ink">{title}</h2>
      <p className="mt-1 text-sm text-status-slate-600">{blurb}</p>
      {rows.length === 0 ? (
        <p className="mt-3 text-sm text-rally-muted">{empty}</p>
      ) : (
        <ul className="mt-2">
          {rows.map((r) => (
            <li
              key={r.id}
              className="flex items-center justify-between gap-2 border-t border-status-slate-100 py-2.5"
            >
              <span className="flex min-w-0 flex-col">
                <b className="text-sm text-rally-ink">{r.name}</b>
                <span className="text-xs text-rally-muted">{r.detail}</span>
              </span>
              <Link
                href={r.href as never}
                className="shrink-0 py-2 text-sm font-bold text-rally-cobalt-700 hover:text-rally-cobalt-900"
              >
                {r.action}
              </Link>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

function weeksAgo(iso: string): string {
  const weeks = Math.floor((Date.now() - new Date(iso).getTime()) / (7 * 24 * 60 * 60 * 1000));
  return weeks <= 1 ? "a week ago" : `${weeks} weeks ago`;
}
