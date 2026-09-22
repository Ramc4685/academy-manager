"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import type { Route } from "next";
import { useInfiniteQuery } from "@tanstack/react-query";
import { RefreshCw } from "lucide-react";

import { listAdminStudents, type AdminStudentView } from "@/lib/api/admin";
import { queryKeys } from "@/lib/query/keys";
import { statText } from "@/lib/ui/load-state";
import { useIsPhone } from "@/lib/use-is-phone";
import { Card } from "@/components/ds/card";
import { Chip } from "@/components/ds/chip";
import { Avatar } from "@/components/ds/avatar";
import { Button } from "@/components/ds/button";
import { PhoneList, PhoneListRow } from "@/components/ds/phone-row";
import { EmptyState } from "@/components/ds/empty-state";
import { ErrorNotice } from "@/components/ds/error-notice";
import { BigNum, Overline } from "@/components/ds/typography";
import {
  FilterBar,
  FilterChip,
  ListToolbar,
  ToolbarSearch,
} from "@/components/ds/list-toolbar";
import { Th } from "@/components/ds/dialog-chrome";
import { duesChip } from "@/lib/people-status";
import {
  ALL_LIFECYCLES,
  OPERATIONAL_LIFECYCLES,
  lifecycleLabel,
  lifecycleName,
  lifecycleVariant,
  type PersonLifecycle,
} from "@/lib/format/lifecycle-copy";

const PAGE_LIMIT = 25;

// Issue #773: filters are DERIVED lifecycles, not the free-text
// students.status this page used to send. "Everyone" is deliberately not the
// default — the directory opens on the people who are still somebody's
// problem today.
//
// Issue #775: these are the People directory's TABS. Every one of them
// carries its own count, because a tab with no number is a question ("are
// there any?") the admin has to answer by clicking it — which is how the
// Left tab stayed a dead end even after the data existed. `states` is
// unchanged and so is each tab's id: the id IS the `lifecycle=` query this
// tab sends.
const LIFECYCLE_FILTERS: { id: string; label: string; states: PersonLifecycle[] }[] = [
  { id: "operational", label: "On the books", states: OPERATIONAL_LIFECYCLES },
  { id: "all", label: "Everyone", states: [] },
  ...ALL_LIFECYCLES.map((state) => ({
    id: state,
    label: lifecycleName(state),
    states: [state],
  })),
];

// The "Everyone" tab counts every state; a single-state tab counts its own.
// A tab whose states are all missing from the payload shows no number rather
// than a confident zero — an older backend sends no counts at all.
function tabCount(
  states: PersonLifecycle[],
  counts: Record<string, number>,
): number | null {
  const wanted = states.length > 0 ? states : ALL_LIFECYCLES;
  const known = wanted.filter((state) => state in counts);
  if (known.length === 0) return null;
  return known.reduce((sum, state) => sum + (counts[state] ?? 0), 0);
}

export default function AdminStudentsPage() {
  const [searchInput, setSearchInput] = useState("");
  const [filterId, setFilterId] = useState<string>("operational");

  const search = searchInput.trim();
  const lifecycle =
    LIFECYCLE_FILTERS.find((f) => f.id === filterId)?.states ?? [];

  const studentsQuery = useInfiniteQuery({
    queryKey: queryKeys.admin.students({
      search,
      lifecycle: filterId,
      limit: PAGE_LIMIT,
    }),
    queryFn: ({ pageParam }) =>
      listAdminStudents({
        search: search || undefined,
        lifecycle,
        limit: PAGE_LIMIT,
        cursor: typeof pageParam === "string" ? pageParam : undefined,
      }),
    initialPageParam: null as string | null,
    getNextPageParam: (lastPage) => lastPage.next_cursor ?? undefined,
    retry: false,
  });

  const students = useMemo(
    () => studentsQuery.data?.pages.flatMap((page) => page.students ?? []) ?? [],
    [studentsQuery.data],
  );
  const hasFilters = Boolean(search) || filterId !== "all";
  // Issue #773: counts come from the backend, over every row that matched the
  // search — not from the 25 rows this client happens to have loaded.
  const counts = studentsQuery.data?.pages[0]?.lifecycle_counts ?? {};

  return (
    <section data-testid="admin-students" className="space-y-6">
      <SummaryCards counts={counts} students={students} state={studentsQuery} />

      <Card p={0}>
        <StudentsToolbar
          search={searchInput}
          filterId={filterId}
          counts={counts}
          onSearchChange={setSearchInput}
          onFilterChange={setFilterId}
          isFetching={studentsQuery.isFetching && !studentsQuery.isFetchingNextPage}
        />

        {studentsQuery.isError ? (
          <ErrorNotice
            testId="admin-students-error"
            className="m-5"
            message="Could not load students. The counts above are unknown, not zero."
            onRetry={() => void studentsQuery.refetch()}
            retrying={studentsQuery.isFetching}
          />
        ) : studentsQuery.isPending ? (
          <div className="p-5">
            <Skeleton />
          </div>
        ) : students.length === 0 ? (
          <EmptyState
            data-testid="admin-students-empty"
            className="p-5"
            title={hasFilters ? "No students match those filters." : "No students registered yet."}
            action={
              hasFilters ? (
                <Button
                  variant="secondary"
                  size="sm"
                  data-testid="admin-students-clear-filters"
                  onClick={() => {
                    setSearchInput("");
                    setFilterId("all");
                  }}
                >
                  Clear filters
                </Button>
              ) : undefined
            }
          />
        ) : (
          <>
            <StudentsList students={students} />
            <StudentsFooter
              loadedCount={students.length}
              hasNextPage={studentsQuery.hasNextPage}
              isFetchingNextPage={studentsQuery.isFetchingNextPage}
              onLoadNext={() => studentsQuery.fetchNextPage()}
            />
          </>
        )}
      </Card>
    </section>
  );
}

// Issue #837: these five numbers are derived from `?? {}` / `?? []` defaults,
// so a failed directory load used to render five confident zeros above the
// words "Could not load students." Until the page has rows, each card shows a
// dash — the count is unknown, not nil.
function SummaryCards({
  counts,
  students,
  state,
}: {
  counts: Record<string, number>;
  students: AdminStudentView[];
  state: { isPending: boolean; isError: boolean };
}) {
  const total = Object.values(counts).reduce((sum, n) => sum + n, 0);
  const paymentRisk = students.filter(
    (student) => student.dues_status === "due" || student.dues_status === "overdue",
  ).length;
  const stat = (value: () => number) => statText(state, () => String(value()));

  // #865: five full-width cards stacked vertically took the whole of a
  // 400x860 screen before the first student appeared. Below `md:` they become
  // one horizontally-scrollable strip — the same five numbers, one screenful
  // higher. Desktop keeps the five-column grid.
  return (
    <div
      data-testid="admin-students-kpis"
      className="flex gap-3 overflow-x-auto pb-1 md:grid md:grid-cols-5 md:gap-4 md:overflow-visible md:pb-0 [&>*]:w-40 [&>*]:shrink-0 md:[&>*]:w-auto"
    >
      <Card p={20} accent="#2563eb">
        <Overline>Students</Overline>
        <BigNum size={32}>{stat(() => total)}</BigNum>
        <p className="mt-1 text-[11px] text-rally-subtle">Everyone on record</p>
      </Card>
      <Card p={20} accent="#10b981">
        <Overline>Active</Overline>
        <BigNum size={32}>{stat(() => counts.active ?? 0)}</BigNum>
        <p className="mt-1 text-[11px] text-rally-subtle">Attending now</p>
      </Card>
      <Card p={20} accent="#f59e0b">
        <Overline>At risk</Overline>
        <BigNum size={32}>{stat(() => counts.at_risk ?? 0)}</BigNum>
        <p className="mt-1 text-[11px] text-rally-subtle">Missed last 3 classes</p>
      </Card>
      <Card p={20} accent="var(--rally-subtle-ink)">
        <Overline>Paused / hold</Overline>
        <BigNum size={32}>{stat(() => (counts.paused ?? 0) + (counts.on_hold ?? 0))}</BigNum>
        <p className="mt-1 text-[11px] text-rally-subtle">Coming back</p>
      </Card>
      <Card p={20} accent="#ef4444">
        <Overline>Payment risk</Overline>
        <BigNum size={32}>{stat(() => paymentRisk)}</BigNum>
        <p className="mt-1 text-[11px] text-rally-subtle">Due or overdue (loaded rows)</p>
      </Card>
    </div>
  );
}

function StudentsToolbar({
  search,
  filterId,
  counts,
  onSearchChange,
  onFilterChange,
  isFetching,
}: {
  search: string;
  filterId: string;
  counts: Record<string, number>;
  onSearchChange: (value: string) => void;
  onFilterChange: (value: string) => void;
  isFetching: boolean;
}) {
  // #897: this toolbar is the reference shape for all three People lists and
  // now lives in the design system, so Families and Users cannot drift from it
  // again.
  return (
    <ListToolbar>
      <FilterBar
        variant="tablist"
        label="People by lifecycle"
        testId="admin-students-tabs"
      >
        {LIFECYCLE_FILTERS.map((filter) => (
          <FilterChip
            key={filter.id}
            variant="tab"
            active={filterId === filter.id}
            label={filter.label}
            count={tabCount(filter.states, counts)}
            testId={`admin-students-filter-${filter.id}`}
            countTestId={`admin-students-filter-count-${filter.id}`}
            onClick={() => onFilterChange(filter.id)}
          />
        ))}
      </FilterBar>

      <ToolbarSearch
        id="admin-students-search"
        label="Search students"
        value={search}
        onChange={onSearchChange}
        placeholder="Search students or parents"
        busy={isFetching}
        busyLabel="Refreshing students"
      />
    </ListToolbar>
  );
}

/**
 * #847: one list, two layouts. The phone rows carry the same `data-testid`s
 * as the table rows and exactly one of the two is mounted, so a row is never
 * two nodes — see `lib/use-is-phone.ts`.
 */
function StudentsList({ students }: { students: AdminStudentView[] }) {
  const isPhone = useIsPhone();
  return isPhone ? (
    <StudentsPhoneList students={students} />
  ) : (
    <StudentsTable students={students} />
  );
}

function StudentsPhoneList({ students }: { students: AdminStudentView[] }) {
  return (
    <PhoneList aria-label="Students" data-testid="admin-students-phone-list">
      {students.map((student) => (
        <PhoneListRow
          key={student.student_id}
          data-testid={`admin-students-row-${student.student_id}`}
          leading={<Avatar name={student.full_name} size={34} />}
          title={student.full_name}
          href={`/admin/students/${student.student_id}` as Route}
          titleTestId={`admin-students-link-${student.student_id}`}
          primary={<DuesChip status={student.dues_status} />}
          actionsLabel={`Actions for ${student.full_name}`}
          actionsTestId={`admin-students-row-actions-${student.student_id}`}
          actions={[
            {
              key: "student",
              label: "Open student",
              href: `/admin/students/${student.student_id}` as Route,
            },
            ...(student.parent_id
              ? [
                  {
                    key: "family",
                    label: "Open family",
                    href: `/admin/families/${encodeURIComponent(student.parent_id)}` as Route,
                  },
                ]
              : []),
          ]}
          // #865: the parent's address is already on line 2 — this makes
          // reaching them a tap instead of a copy-paste.
          contact={{ email: student.parent_email }}
          secondary={
            <>
              <div className="flex flex-wrap items-center gap-2">
                <LifecycleChip
                  state={student.lifecycle}
                  asOf={student.lifecycle_as_of}
                />
                <AttendanceText rate={student.attendance_rate} />
              </div>
              <div className="break-words">
                {student.parent_name || student.parent_email || "Parent on file"}
                {student.parent_email ? ` · ${student.parent_email}` : ""}
              </div>
              <div className="break-words">
                <SessionsSummaryText
                  count={student.active_session_count}
                  total={student.active_session_total}
                  names={student.active_session_names}
                />
              </div>
            </>
          }
        />
      ))}
    </PhoneList>
  );
}

/** The table's attendance bar, as the one line a phone has room for. */
function AttendanceText({ rate }: { rate: number | null }) {
  if (rate === null) {
    return <span className="font-mono text-xs text-rally-subtle">— attendance</span>;
  }
  const pct = Math.round(Math.max(0, Math.min(rate, 1)) * 100);
  return (
    <span className="font-mono text-xs font-bold tabular-nums text-rally-base">
      {pct}% <span className="font-semibold text-rally-subtle">30d</span>
    </span>
  );
}

function SessionsSummaryText({
  count,
  total,
  names,
}: {
  count: number;
  total?: number;
  names?: string[];
}) {
  const listed = names ?? [];
  const sessionTotal = total ?? count;
  if (sessionTotal <= 0) return <>No active session</>;
  if (listed.length === 0) {
    return <>{`${sessionTotal} ${sessionTotal === 1 ? "session" : "sessions"}`}</>;
  }
  const unlisted = Math.max(sessionTotal - listed.length, 0);
  return <>{listed.join(", ") + (unlisted > 0 ? `, +${unlisted} more` : "")}</>;
}

function StudentsTable({ students }: { students: AdminStudentView[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[760px] text-sm">
        <thead>
          <tr className="border-b border-neutral-200 bg-neutral-50 text-left dark:border-neutral-800">
            <Th padding="px-5 py-3">Student</Th>
            <Th padding="px-3 py-3">Parent</Th>
            <Th padding="px-3 py-3">Sessions</Th>
            <Th padding="px-3 py-3">Attendance</Th>
            <Th padding="px-3 py-3">Dues</Th>
            <Th padding="px-5 py-3">Last attendance</Th>
          </tr>
        </thead>
        <tbody>
          {students.map((student) => (
            <tr
              key={student.student_id}
              data-testid={`admin-students-row-${student.student_id}`}
              className="border-b border-neutral-100 transition last:border-0 hover:bg-neutral-50 dark:border-neutral-800"
            >
              <td className="px-5 py-4">
                <Link
                  href={`/admin/students/${student.student_id}`}
                  className="flex items-center gap-3 group focus:outline-none focus:ring-2 focus:ring-rally-cobalt-600 rounded"
                  data-testid={`admin-students-link-${student.student_id}`}
                >
                  <Avatar name={student.full_name} size={34} />
                  <div>
                    <div className="font-semibold text-rally-base group-hover:underline">{student.full_name}</div>
                  </div>
                </Link>
                {/* #847: Lifecycle was the last column of a 7-column table and
                    was the first thing clipped at 1280. It is the answer to
                    "is this person still ours?", so it belongs against the
                    name, not past the fold. */}
                <div className="mt-1.5">
                  <LifecycleChip
                    state={student.lifecycle}
                    asOf={student.lifecycle_as_of}
                  />
                </div>
              </td>
              <td className="px-3 py-4">
                {/* #839: the parent cell was plain text, so the family — and
                    all of this student's money — was only reachable by
                    remembering the name and searching Families for it. */}
                {student.parent_id ? (
                  <Link
                    href={`/admin/families/${encodeURIComponent(student.parent_id)}`}
                    className="block rounded text-rally-base hover:underline focus:outline-none focus:ring-2 focus:ring-rally-cobalt-600"
                    data-testid={`admin-students-family-link-${student.student_id}`}
                  >
                    {student.parent_name || student.parent_email || "Parent on file"}
                  </Link>
                ) : (
                  <div className="text-rally-base">
                    {student.parent_name || student.parent_email || "Parent on file"}
                  </div>
                )}
                <div className="text-xs text-rally-subtle">
                  {student.parent_email ?? "No email on file"}
                </div>
              </td>
              <td className="px-3 py-4">
                <SessionsCell
                  count={student.active_session_count}
                  total={student.active_session_total}
                  names={student.active_session_names}
                />
              </td>
              <td className="px-3 py-4">
                <AttendanceCell rate={student.attendance_rate} />
              </td>
              <td className="px-3 py-4">
                <DuesChip status={student.dues_status} />
              </td>
              <td className="px-5 py-4 font-mono text-[11px] text-rally-subtle">
                {student.last_seen_at ? new Date(student.last_seen_at).toLocaleDateString() : "—"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// Issue #104: the roster needs to say WHICH sessions, not just how many. The
// backend caps the names it sends and reports the distinct-session total
// alongside them, so the remainder is total - listed. `count` is the older
// enrollment-document tally and is only a fallback — it can exceed the total
// when a student holds two active enrollments for one session, and using it
// here would claim a session that does not exist.
function SessionsCell({
  count,
  total,
  names,
}: {
  count: number;
  total?: number;
  names?: string[];
}) {
  const listed = names ?? [];
  const sessionTotal = total ?? count;

  if (sessionTotal <= 0) {
    return <span className="text-xs text-rally-subtle">No active session</span>;
  }
  if (listed.length === 0) {
    // Older payloads carry only the count.
    return (
      <span className="font-mono tabular-nums text-rally-base">
        {sessionTotal} {sessionTotal === 1 ? "session" : "sessions"}
      </span>
    );
  }

  const [first, ...rest] = listed;
  const unlisted = Math.max(sessionTotal - listed.length, 0);
  return (
    <div className="min-w-0 max-w-[15rem]" title={listed.join(", ")}>
      <div className="truncate text-rally-base">{first}</div>
      {(rest.length > 0 || unlisted > 0) && (
        <div className="truncate text-xs text-rally-subtle">
          {rest.length > 0 && rest.join(", ")}
          {rest.length > 0 && unlisted > 0 && ", "}
          {unlisted > 0 && `+${unlisted} more`}
        </div>
      )}
    </div>
  );
}

function AttendanceCell({ rate }: { rate: number | null }) {
  if (rate === null) {
    return <span className="font-mono text-sm text-rally-subtle">—</span>;
  }
  const pct = Math.round(Math.max(0, Math.min(rate, 1)) * 100);
  const tone = pct >= 90 ? "bg-emerald-500" : pct >= 75 ? "bg-amber-500" : "bg-red-500";

  return (
    <div className="min-w-[140px]">
      <div className="mb-1 flex items-center justify-between gap-3">
        <span className="font-mono text-xs font-bold tabular-nums text-rally-base">{pct}%</span>
        <span className="font-mono text-[10px] font-semibold uppercase tracking-chip text-rally-subtle">30d</span>
      </div>
      <div className="h-2 overflow-hidden rounded-sm bg-rally-line">
        <div className={`h-full rounded-sm ${tone}`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

// #897: the labels come from `lib/people-status`, where the Families list
// already reads its Login and Card words — one `Chip` primitive, one casing.
function DuesChip({ status }: { status: AdminStudentView["dues_status"] }) {
  const chip = duesChip(status);
  return <Chip variant={chip.variant} label={chip.label} />;
}

function StudentsFooter({
  loadedCount,
  hasNextPage,
  isFetchingNextPage,
  onLoadNext,
}: {
  loadedCount: number;
  hasNextPage: boolean;
  isFetchingNextPage: boolean;
  onLoadNext: () => void;
}) {
  return (
    <div className="flex flex-col gap-3 border-t border-neutral-200 bg-neutral-50 px-5 py-4 text-rally-muted dark:border-neutral-800 sm:flex-row sm:items-center sm:justify-between">
      <span className="font-mono text-[11px] font-bold uppercase tracking-overline">
        Showing {loadedCount} students
      </span>
      <Button
        variant="secondary"
        size="sm"
        onClick={onLoadNext}
        disabled={!hasNextPage || isFetchingNextPage}
        icon={isFetchingNextPage ? <RefreshCw className="size-3.5 animate-spin" /> : undefined}
      >
        {isFetchingNextPage ? "Loading next page" : "Next page"}
      </Button>
    </div>
  );
}

function Skeleton() {
  return (
    <div className="space-y-2">
      {[0, 1, 2].map((i) => (
        <div key={i} className="h-14 animate-pulse rounded-lg bg-neutral-100 dark:bg-neutral-800" />
      ))}
    </div>
  );
}

/**
 * One chip per person, or nothing. A payload from before #773 (a cached page,
 * a rolled-back backend) carries no lifecycle at all, and a blank cell beats a
 * crashed table.
 */
function LifecycleChip({
  state,
  asOf,
}: {
  state: string | null | undefined;
  asOf?: string | null;
}) {
  const label = lifecycleLabel(state, asOf);
  if (!label) return <span className="text-xs text-rally-subtle">—</span>;
  return <Chip variant={lifecycleVariant(state)} label={label} />;
}
