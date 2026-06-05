"use client";

import { useState } from "react";
import { useParams, useSearchParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  getAdminStudentCertificates,
  getStudentProgress,
  listPrograms,
  placeStudentInLevel,
} from "@/lib/api/curriculum";
import { getActiveAcademyId } from "@/lib/api/client";
import { Card } from "@/components/ds/card";
import { Button } from "@/components/ds/button";

export default function AdminStudentProgressPage() {
  const { studentId } = useParams<{ studentId: string }>();
  const searchParams = useSearchParams();
  const queryClient = useQueryClient();
  const academyId = getActiveAcademyId() ?? "";

  const programIdParam = searchParams.get("program_id") ?? "";
  const [selectedProgramId, setSelectedProgramId] = useState(programIdParam);

  const { data: programs } = useQuery({
    queryKey: ["admin", "programs", academyId],
    queryFn: () => listPrograms(academyId),
    enabled: Boolean(academyId),
  });

  const { data: progress, isLoading, isError } = useQuery({
    queryKey: ["admin", "student-progress", studentId, selectedProgramId],
    queryFn: () => getStudentProgress(studentId, selectedProgramId),
    enabled: Boolean(studentId) && Boolean(selectedProgramId),
  });

  const { data: certificates } = useQuery({
    queryKey: ["admin", "student-certificates", studentId],
    queryFn: () => getAdminStudentCertificates(studentId),
    enabled: Boolean(studentId),
  });

  const [showPlaceForm, setShowPlaceForm] = useState(false);
  const [placeProgramId, setPlaceProgramId] = useState("");
  const [placeLevelId, setPlaceLevelId] = useState("");

  const placeMutation = useMutation({
    mutationFn: () =>
      placeStudentInLevel(studentId, {
        program_id: placeProgramId,
        level_id: placeLevelId,
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: ["admin", "student-progress", studentId],
      });
      setShowPlaceForm(false);
      setPlaceProgramId("");
      setPlaceLevelId("");
    },
  });

  const programList = programs ?? [];
  const certList = certificates ?? [];

  const passedPct =
    progress && progress.total_skills > 0
      ? Math.round((progress.passed_skills / progress.total_skills) * 100)
      : 0;

  return (
    <section data-testid="admin-student-progress" className="space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold">Student Progress</h1>
          <p className="mt-0.5 text-sm text-neutral-500">ID: {studentId}</p>
        </div>
        <Button variant="primary" size="sm" onClick={() => setShowPlaceForm((v) => !v)}>
          {showPlaceForm ? "Cancel" : "Place in Level"}
        </Button>
      </div>

      {/* Program selector */}
      {programList.length > 0 && (
        <div className="flex items-center gap-3">
          <label className="text-sm font-medium text-neutral-600">Program:</label>
          <select
            value={selectedProgramId}
            onChange={(e) => setSelectedProgramId(e.target.value)}
            className="rounded-md border border-neutral-300 px-3 py-1.5 text-sm focus:border-blue-500 focus:outline-none"
          >
            <option value="">Select a program</option>
            {programList.map((p) => (
              <option key={p.program_id} value={p.program_id}>
                {p.name}
              </option>
            ))}
          </select>
        </div>
      )}

      {/* Place in level form */}
      {showPlaceForm && (
        <Card p={20}>
          <h2 className="mb-3 text-sm font-semibold">Place in Level</h2>
          <div className="space-y-3">
            <div>
              <label className="mb-1 block text-xs font-medium text-neutral-600">Program ID</label>
              <input
                type="text"
                value={placeProgramId}
                onChange={(e) => setPlaceProgramId(e.target.value)}
                placeholder="Program ID"
                className="w-full rounded-md border border-neutral-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
              />
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-neutral-600">Level ID</label>
              <input
                type="text"
                value={placeLevelId}
                onChange={(e) => setPlaceLevelId(e.target.value)}
                placeholder="Level ID"
                className="w-full rounded-md border border-neutral-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
              />
            </div>
            {placeMutation.isError && (
              <p className="text-xs text-red-600">Failed to place student. Please try again.</p>
            )}
            <div className="flex justify-end gap-2">
              <Button variant="secondary" size="sm" onClick={() => setShowPlaceForm(false)}>
                Cancel
              </Button>
              <Button
                variant="primary"
                size="sm"
                disabled={!placeProgramId.trim() || !placeLevelId.trim() || placeMutation.isPending}
                onClick={() => placeMutation.mutate()}
              >
                {placeMutation.isPending ? "Placing..." : "Place Student"}
              </Button>
            </div>
          </div>
        </Card>
      )}

      {/* Progress summary */}
      {!selectedProgramId ? (
        <p className="text-sm text-neutral-500">Select a program to view progress.</p>
      ) : isError ? (
        <p role="alert" className="rounded-md bg-red-50 p-3 text-sm text-red-700">
          Could not load progress.
        </p>
      ) : isLoading ? (
        <Skeleton />
      ) : progress ? (
        <Card p={20}>
          <div className="space-y-4">
            <div className="flex items-start justify-between gap-4">
              <div>
                <p className="text-lg font-semibold">{progress.program_name}</p>
                <p className="text-sm text-neutral-500">
                  Current level:{" "}
                  <span className="font-medium text-rally-base">
                    {progress.current_level_name ?? "Not placed"}
                  </span>
                </p>
              </div>
              {progress.level_up_status && (
                <span className="rounded-full bg-yellow-100 px-3 py-1 text-xs font-semibold text-yellow-800">
                  {progress.level_up_status}
                </span>
              )}
            </div>

            {/* Progress bar */}
            <div>
              <div className="mb-1 flex justify-between text-xs text-neutral-500">
                <span>Skills passed</span>
                <span>
                  {progress.passed_skills} / {progress.total_skills} ({passedPct}%)
                </span>
              </div>
              <div className="h-2.5 w-full overflow-hidden rounded-full bg-neutral-200">
                <div
                  className="h-full rounded-full bg-green-500 transition-all duration-500"
                  style={{ width: `${passedPct}%` }}
                />
              </div>
            </div>

            {/* Skill counts */}
            <div className="grid grid-cols-3 gap-3">
              <StatTile label="Passed" value={progress.passed_skills} color="#059669" />
              <StatTile label="In Progress" value={progress.in_progress_skills} color="#d97706" />
              <StatTile label="Not Started" value={progress.not_started_skills} color="#9ca3af" />
            </div>
          </div>
        </Card>
      ) : null}

      {/* Certificates */}
      <div>
        <h2 className="mb-3 text-lg font-semibold">Certificates</h2>
        {certList.length === 0 ? (
          <p className="text-sm text-neutral-500">No certificates yet.</p>
        ) : (
          <div className="space-y-2">
            {certList.map((cert) => (
              <div
                key={cert.cert_id}
                className="flex items-center justify-between rounded-lg border border-neutral-200 px-4 py-3 dark:border-neutral-800"
              >
                <div>
                  <p className="font-medium text-rally-base">{cert.level_name}</p>
                  <p className="text-xs text-neutral-500">
                    {cert.program_name} · #{cert.cert_number}
                  </p>
                </div>
                <div className="text-right text-xs text-neutral-400">
                  <p>Completed {formatDate(cert.completed_at)}</p>
                  <p>Issued {formatDate(cert.issued_at)}</p>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </section>
  );
}

function StatTile({
  label,
  value,
  color,
}: {
  label: string;
  value: number;
  color: string;
}) {
  return (
    <div
      className="rounded-lg px-3 py-2.5 text-center"
      style={{ background: `${color}18`, border: `1px solid ${color}30` }}
    >
      <p className="text-xl font-bold" style={{ color }}>
        {value}
      </p>
      <p className="mt-0.5 text-[11px] font-medium text-neutral-500">{label}</p>
    </div>
  );
}

function formatDate(value: string): string {
  return new Date(value).toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

function Skeleton() {
  return (
    <div className="space-y-3">
      <div className="h-28 animate-pulse rounded-lg bg-neutral-100 dark:bg-neutral-800" />
    </div>
  );
}
