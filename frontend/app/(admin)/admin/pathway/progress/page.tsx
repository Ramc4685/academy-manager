"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import {
  getAdminPathwayProgress,
  listPrograms,
  type ProgressNextAction,
  type StudentProgressOverview,
} from "@/lib/api/curriculum";
import { getActiveAcademyId } from "@/lib/api/client";
import { buildStudentProgressHref } from "@/lib/navigation/admin-student-progress-return";
import { Card } from "@/components/ds/card";

const progressOverviewEnabled = process.env.NEXT_PUBLIC_SKILL_PROGRESS_OVERVIEW === "1";

const nextActionOptions: { value: ProgressNextAction; label: string }[] = [
  { value: "place_in_level", label: "Place in level" },
  { value: "continue_practice", label: "Continue practice" },
  { value: "record_tests", label: "Record tests" },
  { value: "recommend_level_up", label: "Recommend level up" },
  { value: "awaiting_admin_approval", label: "Awaiting approval" },
  { value: "certificate_issued", label: "Certificate issued" },
];

const nextActionLabels = Object.fromEntries(
  nextActionOptions.map((option) => [option.value, option.label]),
) as Record<ProgressNextAction, string>;

export default function AdminPathwayProgressPage() {
  const academyId = getActiveAcademyId() ?? "";
  const [selectedProgramId, setSelectedProgramId] = useState("");
  const [nextAction, setNextAction] = useState<ProgressNextAction | "">("");

  const { data: programs, isLoading: programsLoading, isError: programsError } = useQuery({
    queryKey: ["admin", "programs", academyId],
    queryFn: () => listPrograms(academyId),
    enabled: progressOverviewEnabled && Boolean(academyId),
  });

  const programList = useMemo(() => programs ?? [], [programs]);

  useEffect(() => {
    if (!selectedProgramId && programList.length > 0) {
      setSelectedProgramId(programList[0].program_id);
    }
  }, [programList, selectedProgramId]);

  const {
    data: rows,
    isLoading: rowsLoading,
    isError: rowsError,
  } = useQuery({
    queryKey: ["admin", "pathway-progress", selectedProgramId, nextAction],
    queryFn: () =>
      getAdminPathwayProgress(
        selectedProgramId,
        nextAction === "" ? undefined : nextAction,
      ),
    enabled: progressOverviewEnabled && Boolean(selectedProgramId),
    staleTime: 2 * 60 * 1000,
  });

  if (!progressOverviewEnabled) {
    return (
      <section data-testid="admin-pathway-progress-disabled" className="space-y-3">
        <h1 className="text-2xl font-semibold">Pathway Progress</h1>
        <p className="text-sm text-neutral-500">Progress overview is not enabled.</p>
      </section>
    );
  }

  const progressRows = rows ?? [];

  return (
    <section data-testid="admin-pathway-progress" className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">Pathway Progress</h1>
        <p className="mt-0.5 text-sm text-neutral-500">
          Student level placement, skill completion, and next actions
        </p>
      </div>

      <Card p={16}>
        <div className="grid gap-3 md:grid-cols-[minmax(0,1fr)_240px]">
          <label className="block">
            <span className="mb-1 block text-xs font-medium text-neutral-600">Program</span>
            <select
              value={selectedProgramId}
              onChange={(event) => setSelectedProgramId(event.target.value)}
              className="w-full rounded-md border border-neutral-300 bg-white px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
              disabled={programsLoading || programList.length === 0}
            >
              {programList.length === 0 ? (
                <option value="">No programs</option>
              ) : (
                programList.map((program) => (
                  <option key={program.program_id} value={program.program_id}>
                    {program.name}
                  </option>
                ))
              )}
            </select>
          </label>

          <label className="block">
            <span className="mb-1 block text-xs font-medium text-neutral-600">Next action</span>
            <select
              value={nextAction}
              onChange={(event) => setNextAction(event.target.value as ProgressNextAction | "")}
              className="w-full rounded-md border border-neutral-300 bg-white px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
            >
              <option value="">All actions</option>
              {nextActionOptions.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
        </div>
      </Card>

      {programsError || rowsError ? (
        <p role="alert" className="rounded-md bg-red-50 p-3 text-sm text-red-700">
          Could not load pathway progress.
        </p>
      ) : rowsLoading || programsLoading ? (
        <OverviewSkeleton />
      ) : progressRows.length === 0 ? (
        <p className="text-sm text-neutral-500">No students match this view.</p>
      ) : (
        <>
          <SummaryTiles rows={progressRows} />
          <ProgressTable rows={progressRows} />
        </>
      )}
    </section>
  );
}

function SummaryTiles({ rows }: { rows: StudentProgressOverview[] }) {
  const placed = rows.filter((row) => row.current_level_id !== null).length;
  const testReady = rows.filter((row) => row.test_ready_count > 0).length;
  const awaitingApproval = rows.filter(
    (row) => row.next_action === "awaiting_admin_approval",
  ).length;
  const certificates = rows.reduce((total, row) => total + row.certificate_count, 0);

  return (
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
      <StatTile label="Students" value={rows.length} />
      <StatTile label="Placed" value={placed} />
      <StatTile label="Test Ready" value={testReady} />
      <StatTile label="Certificates" value={certificates} />
      {awaitingApproval > 0 && <StatTile label="Need Approval" value={awaitingApproval} />}
    </div>
  );
}

function StatTile({ label, value }: { label: string; value: number }) {
  return (
    <Card p={16}>
      <p className="text-xs font-medium uppercase tracking-wide text-neutral-500">{label}</p>
      <p className="mt-1 text-2xl font-semibold text-rally-base">{value}</p>
    </Card>
  );
}

function ProgressTable({ rows }: { rows: StudentProgressOverview[] }) {
  return (
    <div className="overflow-hidden rounded-lg border border-neutral-200 bg-white">
      <div className="overflow-x-auto">
        <table className="min-w-full divide-y divide-neutral-200 text-sm">
          <thead className="bg-neutral-50 text-xs uppercase tracking-wide text-neutral-500">
            <tr>
              <th className="px-4 py-3 text-left font-semibold">Student</th>
              <th className="px-4 py-3 text-left font-semibold">Level</th>
              <th className="px-4 py-3 text-left font-semibold">Required</th>
              <th className="px-4 py-3 text-left font-semibold">Total</th>
              <th className="px-4 py-3 text-left font-semibold">Next action</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-neutral-100">
            {rows.map((row) => {
              const requiredPct = percent(row.required_skills_passed, row.required_skill_count);
              const detailHref = buildStudentProgressHref({
                studentId: row.student_id,
                programId: row.program_id,
                returnTo: "/admin/pathway/progress",
                returnLabel: "Back to pathway progress",
              });
              return (
                <tr key={row.student_id} className="hover:bg-neutral-50">
                  <td className="px-4 py-3">
                    <Link
                      href={detailHref as Parameters<typeof Link>[0]["href"]}
                      className="font-semibold text-blue-700 hover:text-blue-900"
                    >
                      {row.student_name}
                    </Link>
                    <p className="mt-0.5 text-xs text-neutral-500">{row.program_name}</p>
                  </td>
                  <td className="px-4 py-3 text-neutral-700">
                    {row.current_level_name ?? "Not placed"}
                  </td>
                  <td className="px-4 py-3 text-neutral-700">
                    {row.required_skills_passed}/{row.required_skill_count}
                    {requiredPct !== null && (
                      <span className="ml-1 text-xs text-neutral-500">({requiredPct}%)</span>
                    )}
                  </td>
                  <td className="px-4 py-3 text-neutral-700">
                    {row.total_skills_passed}/{row.total_skill_count}
                  </td>
                  <td className="px-4 py-3 text-neutral-700">
                    {nextActionLabels[row.next_action]}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function percent(numerator: number, denominator: number): number | null {
  if (denominator <= 0) return null;
  return Math.round((numerator / denominator) * 100);
}

function OverviewSkeleton() {
  return (
    <div className="space-y-3">
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {[0, 1, 2, 3].map((index) => (
          <div key={index} className="h-20 animate-pulse rounded-lg bg-neutral-100" />
        ))}
      </div>
      <div className="h-56 animate-pulse rounded-lg bg-neutral-100" />
    </div>
  );
}
