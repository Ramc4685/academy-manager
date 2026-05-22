"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { useInfiniteQuery } from "@tanstack/react-query";
import { RefreshCw, Search } from "lucide-react";

import { listAdminStudents, type AdminStudentView } from "@/lib/api/admin";
import { queryKeys } from "@/lib/query/keys";
import { Card } from "@/components/ds/card";
import { Chip } from "@/components/ds/chip";
import { Avatar } from "@/components/ds/avatar";
import { Button } from "@/components/ds/button";
import { BigNum, Overline } from "@/components/ds/typography";

const PAGE_LIMIT = 25;

const STATUS_FILTERS = [
  { id: "all", label: "All" },
  { id: "active", label: "Active" },
  { id: "paused", label: "Paused" },
  { id: "inactive", label: "Inactive" },
] as const;

type StatusFilter = (typeof STATUS_FILTERS)[number]["id"];

export default function AdminStudentsPage() {
  const [searchInput, setSearchInput] = useState("");
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");

  const search = searchInput.trim();
  const status = statusFilter === "all" ? undefined : statusFilter;

  const studentsQuery = useInfiniteQuery({
    queryKey: queryKeys.admin.students({ search, status, limit: PAGE_LIMIT }),
    queryFn: ({ pageParam }) =>
      listAdminStudents({
        search: search || undefined,
        status,
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
  const hasFilters = Boolean(search || status);

  return (
    <section data-testid="admin-students" className="space-y-6">
      <SummaryCards students={students} />

      <Card p={0}>
        <StudentsToolbar
          search={searchInput}
          statusFilter={statusFilter}
          onSearchChange={setSearchInput}
          onStatusChange={setStatusFilter}
          isFetching={studentsQuery.isFetching && !studentsQuery.isFetchingNextPage}
        />

        {studentsQuery.isError ? (
          <div
            role="alert"
            data-testid="admin-students-error"
            className="m-5 rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-700"
          >
            Could not load students.
          </div>
        ) : studentsQuery.isPending ? (
          <div className="p-5">
            <Skeleton />
          </div>
        ) : students.length === 0 ? (
          <p className="p-5 text-sm text-rally-subtle" data-testid="admin-students-empty">
            {hasFilters ? "No students match those filters." : "No students registered yet."}
          </p>
        ) : (
          <>
            <StudentsTable students={students} />
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

function SummaryCards({ students }: { students: AdminStudentView[] }) {
  const active = students.filter((student) => student.status === "active").length;
  const paused = students.filter((student) => student.status === "paused").length;
  const paymentRisk = students.filter(
    (student) => student.dues_status === "due" || student.dues_status === "overdue",
  ).length;

  return (
    <div className="grid gap-4 md:grid-cols-4">
      <Card p={20} accent="#2563eb">
        <Overline>Students</Overline>
        <BigNum size={32}>{students.length}</BigNum>
        <p className="mt-1 text-[11px] text-rally-subtle">Current result set</p>
      </Card>
      <Card p={20} accent="#10b981">
        <Overline>Active</Overline>
        <BigNum size={32}>{active}</BigNum>
        <p className="mt-1 text-[11px] text-rally-subtle">Currently enrolled</p>
      </Card>
      <Card p={20} accent="#94a3b8">
        <Overline>Paused</Overline>
        <BigNum size={32}>{paused}</BigNum>
        <p className="mt-1 text-[11px] text-rally-subtle">Temporarily paused</p>
      </Card>
      <Card p={20} accent="#ef4444">
        <Overline>Payment risk</Overline>
        <BigNum size={32}>{paymentRisk}</BigNum>
        <p className="mt-1 text-[11px] text-rally-subtle">Due or overdue</p>
      </Card>
    </div>
  );
}

function StudentsToolbar({
  search,
  statusFilter,
  onSearchChange,
  onStatusChange,
  isFetching,
}: {
  search: string;
  statusFilter: StatusFilter;
  onSearchChange: (value: string) => void;
  onStatusChange: (value: StatusFilter) => void;
  isFetching: boolean;
}) {
  return (
    <div className="flex flex-col gap-3 border-b border-neutral-200 bg-white px-5 py-4 dark:border-neutral-800 dark:bg-neutral-950 lg:flex-row lg:items-center lg:justify-between">
      <div className="flex flex-wrap items-center gap-2">
        {STATUS_FILTERS.map((filter) => {
          const active = statusFilter === filter.id;
          return (
            <button
              key={filter.id}
              type="button"
              onClick={() => onStatusChange(filter.id)}
              className={`inline-flex h-8 items-center rounded-md px-3 font-body text-[13px] font-semibold transition ${
                active
                  ? "bg-rally-ink text-white"
                  : "bg-transparent text-rally-muted hover:bg-neutral-100"
              }`}
            >
              {filter.label}
            </button>
          );
        })}
      </div>

      <div className="relative min-w-0 lg:w-[320px]">
        <label htmlFor="admin-students-search" className="sr-only">
          Search students
        </label>
        <Search
          aria-hidden="true"
          className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-rally-muted"
        />
        <input
          id="admin-students-search"
          value={search}
          onChange={(event) => onSearchChange(event.target.value)}
          placeholder="Search students or parents"
          className="h-10 w-full rounded-md border border-neutral-200 bg-white pl-9 pr-9 font-body text-sm text-rally-base outline-none transition placeholder:text-rally-subtle focus:border-rally-cobalt-600 focus:ring-2 focus:ring-rally-cobalt-600/15"
        />
        {isFetching && (
          <RefreshCw
            aria-label="Refreshing students"
            className="absolute right-3 top-1/2 size-4 -translate-y-1/2 animate-spin text-rally-muted"
          />
        )}
      </div>
    </div>
  );
}

function mapStatus(s: string) {
  if (s === "active") return "enrolled";
  if (s === "paused") return "paused";
  if (s === "inactive") return "expired";
  return "manual";
}

function StudentsTable({ students }: { students: AdminStudentView[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[860px] text-sm">
        <thead>
          <tr className="border-b border-neutral-200 bg-neutral-50 text-left dark:border-neutral-800">
            <th className="px-5 py-3 font-mono text-[10px] font-bold uppercase tracking-overline text-rally-muted">Student</th>
            <th className="px-3 py-3 font-mono text-[10px] font-bold uppercase tracking-overline text-rally-muted">Parent</th>
            <th className="px-3 py-3 text-right font-mono text-[10px] font-bold uppercase tracking-overline text-rally-muted">Sessions</th>
            <th className="px-3 py-3 font-mono text-[10px] font-bold uppercase tracking-overline text-rally-muted">Attendance</th>
            <th className="px-3 py-3 font-mono text-[10px] font-bold uppercase tracking-overline text-rally-muted">Dues</th>
            <th className="px-3 py-3 font-mono text-[10px] font-bold uppercase tracking-overline text-rally-muted">Last attendance</th>
            <th className="px-5 py-3 font-mono text-[10px] font-bold uppercase tracking-overline text-rally-muted">Status</th>
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
              </td>
              <td className="px-3 py-4">
                <div className="text-rally-base">{student.parent_name || student.parent_email || "Parent on file"}</div>
                <div className="text-xs text-rally-subtle">
                  {student.parent_email ?? "No email on file"}
                </div>
              </td>
              <td className="px-3 py-4 text-right font-mono tabular-nums text-rally-base">
                {student.active_session_count}
              </td>
              <td className="px-3 py-4">
                <AttendanceCell rate={student.attendance_rate} />
              </td>
              <td className="px-3 py-4">
                <DuesChip status={student.dues_status} />
              </td>
              <td className="px-3 py-4 font-mono text-[11px] text-rally-subtle">
                {student.last_seen_at ? new Date(student.last_seen_at).toLocaleDateString() : "—"}
              </td>
              <td className="px-5 py-4">
                <Chip variant={mapStatus(student.status)} label={student.status.toUpperCase()} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
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

function DuesChip({ status }: { status: AdminStudentView["dues_status"] }) {
  if (status === "current") return <Chip variant="paid" label="CURRENT" />;
  if (status === "due") return <Chip variant="pending" label="DUE" />;
  return <Chip variant="overdue" label="OVERDUE" />;
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
