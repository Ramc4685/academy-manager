"use client";

import { useEffect, useState } from "react";
import { useParams, useSearchParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CircleHelp } from "lucide-react";

import {
  getAdminStudentCertificates,
  getAdminStudentPassport,
  getFullPathway,
  getStudentProgress,
  listPrograms,
  placeStudentInLevel,
  recordAdminTestAttempt,
  updateAdminSkillStatus,
  type SkillPassportEntry,
  type SkillStatus,
} from "@/lib/api/curriculum";
import { getAdminStudent } from "@/lib/api/v2/students";
import { getActiveAcademyId } from "@/lib/api/client";
import { Card } from "@/components/ds/card";
import { Button } from "@/components/ds/button";

const STATUS_LABELS: Record<SkillStatus, string> = {
  NOT_STARTED: "Not started",
  INTRODUCED: "Introduced",
  LEARNING: "Learning",
  PRACTICING: "Practicing",
  TEST_READY: "Test ready",
  PASSED: "Passed",
  NEEDS_REVIEW: "Needs review",
};

const ADMIN_SETTABLE_STATUSES: SkillStatus[] = [
  "INTRODUCED",
  "LEARNING",
  "PRACTICING",
  "TEST_READY",
  "NEEDS_REVIEW",
];

const TEST_ATTEMPT_HINT =
  "Attempts = total tries. Successes = correct tries. Examples: 1/1 means one correct try; 10/7 passes at 70%; 10/5 needs review.";

export default function AdminStudentProgressPage() {
  const { studentId } = useParams<{ studentId: string }>();
  const searchParams = useSearchParams();
  const queryClient = useQueryClient();
  const academyId = getActiveAcademyId() ?? "";

  const programIdParam = searchParams.get("program_id") ?? "";
  const [selectedProgramId, setSelectedProgramId] = useState(programIdParam);
  const [showPlaceForm, setShowPlaceForm] = useState(false);
  const [placeProgramId, setPlaceProgramId] = useState("");
  const [placeLevelId, setPlaceLevelId] = useState("");

  const { data: student } = useQuery({
    queryKey: ["admin", "student-detail", studentId],
    queryFn: () => getAdminStudent(studentId),
    enabled: Boolean(studentId),
  });

  const { data: programs } = useQuery({
    queryKey: ["admin", "programs", academyId],
    queryFn: () => listPrograms(academyId),
    enabled: Boolean(academyId),
  });

  useEffect(() => {
    if (!selectedProgramId && programs && programs.length > 0) {
      setSelectedProgramId(programs[0].program_id);
    }
  }, [programs, selectedProgramId]);

  useEffect(() => {
    if (showPlaceForm && selectedProgramId && !placeProgramId) {
      setPlaceProgramId(selectedProgramId);
    }
  }, [placeProgramId, selectedProgramId, showPlaceForm]);

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

  const {
    data: passport,
    isLoading: passportLoading,
    isError: passportError,
  } = useQuery({
    queryKey: ["admin", "student-passport", studentId, selectedProgramId],
    queryFn: () => getAdminStudentPassport(studentId, selectedProgramId),
    enabled:
      Boolean(studentId) &&
      Boolean(selectedProgramId) &&
      Boolean(progress?.current_level_id),
  });

  const { data: placePathway } = useQuery({
    queryKey: ["admin", "pathway", placeProgramId],
    queryFn: () => getFullPathway(placeProgramId),
    enabled: showPlaceForm && Boolean(placeProgramId),
  });

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
      setSelectedProgramId(placeProgramId);
      setPlaceLevelId("");
    },
  });

  const programList = programs ?? [];
  const placeLevels = placePathway?.levels.map((entry) => entry.level) ?? [];
  const certList = certificates ?? [];

  const passedPct =
    progress && progress.total_skills > 0
      ? Math.round((progress.passed_skills / progress.total_skills) * 100)
      : 0;

  return (
    <section data-testid="admin-student-progress" className="space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold">
            {student?.full_name ?? "Student Progress"}
          </h1>
          <p className="mt-0.5 text-sm text-neutral-500">Skill pathway progress</p>
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
              <label className="mb-1 block text-xs font-medium text-neutral-600">Program</label>
              <select
                value={placeProgramId}
                onChange={(e) => {
                  setPlaceProgramId(e.target.value);
                  setPlaceLevelId("");
                }}
                className="w-full rounded-md border border-neutral-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
              >
                <option value="">Select a program</option>
                {programList.map((program) => (
                  <option key={program.program_id} value={program.program_id}>
                    {program.name}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-neutral-600">Level</label>
              <select
                value={placeLevelId}
                onChange={(e) => setPlaceLevelId(e.target.value)}
                className="w-full rounded-md border border-neutral-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
                disabled={!placeProgramId || placeLevels.length === 0}
              >
                <option value="">Select a level</option>
                {placeLevels.map((level) => (
                  <option key={level.level_id} value={level.level_id}>
                    Level {level.sequence}: {level.name}
                  </option>
                ))}
              </select>
              {placeProgramId && placeLevels.length === 0 && (
                <p className="mt-1 text-xs text-neutral-500">
                  No levels found for this program.
                </p>
              )}
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

      {progress?.current_level_id && (
        <SkillPassportSection
          studentId={studentId}
          skills={passport ?? []}
          isLoading={passportLoading}
          isError={passportError}
          onUpdated={() => {
            void queryClient.invalidateQueries({
              queryKey: ["admin", "student-passport", studentId, selectedProgramId],
            });
            void queryClient.invalidateQueries({
              queryKey: ["admin", "student-progress", studentId, selectedProgramId],
            });
          }}
        />
      )}

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

function SkillPassportSection({
  studentId,
  skills,
  isLoading,
  isError,
  onUpdated,
}: {
  studentId: string;
  skills: SkillPassportEntry[];
  isLoading: boolean;
  isError: boolean;
  onUpdated: () => void;
}) {
  return (
    <div>
      <h2 className="mb-3 text-lg font-semibold">Level Skills</h2>
      {isError ? (
        <p role="alert" className="rounded-md bg-red-50 p-3 text-sm text-red-700">
          Could not load skills.
        </p>
      ) : isLoading ? (
        <div className="space-y-3">
          {[0, 1, 2].map((index) => (
            <div key={index} className="h-24 animate-pulse rounded-lg bg-neutral-100" />
          ))}
        </div>
      ) : skills.length === 0 ? (
        <p className="text-sm text-neutral-500">No skills found for this level.</p>
      ) : (
        <div className="space-y-3">
          {skills.map((entry) => (
            <AdminSkillRow
              key={entry.skill_id}
              entry={entry}
              studentId={studentId}
              onUpdated={onUpdated}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function AdminSkillRow({
  entry,
  studentId,
  onUpdated,
}: {
  entry: SkillPassportEntry;
  studentId: string;
  onUpdated: () => void;
}) {
  const [showTestForm, setShowTestForm] = useState(false);
  const [attemptsCount, setAttemptsCount] = useState("1");
  const [successCount, setSuccessCount] = useState("1");
  const [notes, setNotes] = useState("");

  const statusMutation = useMutation({
    mutationFn: (status: SkillStatus) =>
      updateAdminSkillStatus(studentId, entry.skill_id, {
        program_id: entry.program_id,
        level_id: entry.level_id,
        status,
      }),
    onSuccess: onUpdated,
  });

  const testMutation = useMutation({
    mutationFn: () =>
      recordAdminTestAttempt(studentId, entry.skill_id, {
        program_id: entry.program_id,
        level_id: entry.level_id,
        attempts_count: parseInt(attemptsCount, 10),
        success_count: parseInt(successCount, 10),
        notes: notes.trim() || undefined,
      }),
    onSuccess: () => {
      onUpdated();
      setShowTestForm(false);
      setAttemptsCount("1");
      setSuccessCount("1");
      setNotes("");
    },
  });

  const canChangeStatus = entry.status !== "PASSED";
  const currentStatusIsSettable = ADMIN_SETTABLE_STATUSES.includes(entry.status);

  return (
    <div className="rounded-lg border border-neutral-200 bg-white p-4">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-sm font-semibold text-rally-base">
              {entry.sequence}. {entry.skill_name}
            </span>
            {entry.is_required && (
              <span className="rounded-full bg-red-50 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider text-red-600">
                Required
              </span>
            )}
          </div>
          {entry.skill_description && (
            <p className="mt-1 text-sm text-neutral-500">{entry.skill_description}</p>
          )}
          {entry.test_attempt_count > 0 && (
            <p className="mt-2 text-xs text-neutral-500">
              {entry.test_attempt_count} test attempt
              {entry.test_attempt_count === 1 ? "" : "s"}
              {entry.last_tested_at
                ? ` · last ${formatDate(entry.last_tested_at)}`
                : ""}
              {entry.last_test_passed !== null
                ? ` · ${entry.last_test_passed ? "passed" : "failed"}`
                : ""}
            </p>
          )}
        </div>
        <div className="flex shrink-0 flex-wrap items-center gap-2">
          <select
            value={entry.status}
            onChange={(event) => statusMutation.mutate(event.target.value as SkillStatus)}
            disabled={!canChangeStatus || statusMutation.isPending}
            className="min-h-[36px] rounded-md border border-neutral-300 bg-white px-2 py-1.5 text-xs font-medium focus:border-blue-500 focus:outline-none disabled:cursor-not-allowed disabled:opacity-60"
          >
            {!currentStatusIsSettable && (
              <option value={entry.status}>{STATUS_LABELS[entry.status]}</option>
            )}
            {ADMIN_SETTABLE_STATUSES.map((status) => (
              <option key={status} value={status}>
                {STATUS_LABELS[status]}
              </option>
            ))}
          </select>
          <Button
            variant="secondary"
            size="sm"
            onClick={() => setShowTestForm((value) => !value)}
          >
            {showTestForm ? "Cancel" : "Record Test"}
          </Button>
        </div>
      </div>

      {statusMutation.isError && (
        <p className="mt-2 text-xs text-red-600">Failed to update skill status.</p>
      )}

      {showTestForm && (
        <div className="mt-4 rounded-lg bg-neutral-50 p-3">
          <div className="grid gap-3 sm:grid-cols-2">
            <label className="block">
              <span className="mb-1 flex items-center gap-1 text-xs font-medium text-neutral-600">
                Attempts
                <FieldHint message={TEST_ATTEMPT_HINT} />
              </span>
              <input
                type="number"
                min="1"
                value={attemptsCount}
                onChange={(event) => setAttemptsCount(event.target.value)}
                className="w-full rounded-md border border-neutral-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
              />
            </label>
            <label className="block">
              <span className="mb-1 flex items-center gap-1 text-xs font-medium text-neutral-600">
                Successes
                <FieldHint message={TEST_ATTEMPT_HINT} align="end" />
              </span>
              <input
                type="number"
                min="0"
                value={successCount}
                onChange={(event) => setSuccessCount(event.target.value)}
                className="w-full rounded-md border border-neutral-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
              />
            </label>
          </div>
          <label className="mt-3 block">
            <span className="mb-1 block text-xs font-medium text-neutral-600">
              Notes
            </span>
            <input
              type="text"
              value={notes}
              onChange={(event) => setNotes(event.target.value)}
              placeholder="Optional observation"
              className="w-full rounded-md border border-neutral-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
            />
          </label>
          {testMutation.isError && (
            <p className="mt-2 text-xs text-red-600">Failed to record test.</p>
          )}
          <div className="mt-3 flex justify-end">
            <Button
              variant="primary"
              size="sm"
              disabled={testMutation.isPending}
              onClick={() => testMutation.mutate()}
            >
              {testMutation.isPending ? "Saving..." : "Save Test"}
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}

function FieldHint({
  message,
  align = "start",
}: {
  message: string;
  align?: "start" | "end";
}) {
  return (
    <span
      tabIndex={0}
      aria-label={message}
      className="group relative inline-flex text-neutral-400 focus:outline-none"
    >
      <CircleHelp className="size-3.5" aria-hidden="true" />
      <span
        role="tooltip"
        className={`pointer-events-none absolute top-5 z-20 w-64 rounded-md bg-neutral-900 px-3 py-2 text-left text-[11px] font-medium leading-4 text-white opacity-0 shadow-lg transition-opacity group-hover:opacity-100 group-focus:opacity-100 ${
          align === "end" ? "right-0" : "left-0"
        }`}
      >
        {message}
      </span>
    </span>
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
