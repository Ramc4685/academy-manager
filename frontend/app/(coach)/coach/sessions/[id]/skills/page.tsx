"use client";

import { use, useMemo, useState } from "react";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  bulkUpdateCoachSessionSkillStatus,
  getCoachSessionSkills,
  type CoachSessionSkillsStudent,
  type CoachSkillGap,
  type CoachSkillGroup,
} from "@/lib/api/coach";
import { updateSkillStatus, type SkillStatus } from "@/lib/api/curriculum";
import { queryKeys } from "@/lib/query/keys";

const STATUS_OPTIONS: SkillStatus[] = [
  "INTRODUCED",
  "LEARNING",
  "PRACTICING",
  "TEST_READY",
  "PASSED",
  "NEEDS_REVIEW",
];

const STATUS_LABELS: Record<SkillStatus, string> = {
  NOT_STARTED: "Not started",
  INTRODUCED: "Introduced",
  LEARNING: "Learning",
  PRACTICING: "Practicing",
  TEST_READY: "Test ready",
  PASSED: "Passed",
  NEEDS_REVIEW: "Needs review",
};

function todayISO(): string {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(
    now.getDate(),
  ).padStart(2, "0")}`;
}

interface PageProps {
  params: Promise<{ id: string }>;
  searchParams: Promise<{ date?: string; program_id?: string }>;
}

export default function CoachSessionSkillsPage({ params, searchParams }: PageProps) {
  const { id } = use(params);
  const { date: dateParam, program_id: programId } = use(searchParams);
  const occurrenceId = decodeURIComponent(id);
  const date = dateParam ?? todayISO();
  const queryClient = useQueryClient();
  const [mode, setMode] = useState<"skill" | "student">("skill");

  const queryKey = queryKeys.coach.sessionSkills(occurrenceId, date, programId);
  const { data, isLoading, isError, refetch } = useQuery({
    queryKey,
    queryFn: () => getCoachSessionSkills(occurrenceId, { date, programId }),
    staleTime: 2 * 60 * 1000,
  });

  return (
    <section data-testid="coach-session-skills" className="space-y-4">
      <header className="space-y-2">
        <Link
          href={`/coach/sessions/${encodeURIComponent(occurrenceId)}?date=${date}` as Parameters<
            typeof Link
          >[0]["href"]}
          className="text-sm font-medium text-blue-600"
        >
          Back to session
        </Link>
        <div>
          <h1 className="text-xl font-semibold">Skill updates</h1>
          <p className="text-sm text-neutral-500">
            {data ? `${data.title} · ${data.roster.length} students` : date}
          </p>
        </div>
      </header>

      {isError && (
        <div role="alert" className="rounded-md bg-red-50 p-3 text-sm text-red-700">
          <p>Couldn&apos;t load skill updates. Try again.</p>
          <button onClick={() => void refetch()} className="mt-2 min-h-touch rounded-md border px-3">
            Retry
          </button>
        </div>
      )}

      {isLoading && <div className="h-40 animate-pulse rounded-lg bg-neutral-100" />}

      {data && (
        <>
          <div className="grid grid-cols-2 gap-2 rounded-lg bg-neutral-100 p-1">
            <ModeButton active={mode === "skill"} onClick={() => setMode("skill")}>
              By skill
            </ModeButton>
            <ModeButton active={mode === "student"} onClick={() => setMode("student")}>
              By student
            </ModeButton>
          </div>

          {mode === "skill" ? (
            <BySkillWorkspace
              occurrenceId={occurrenceId}
              groups={data.skill_groups}
              students={data.students}
              onUpdated={() => void queryClient.invalidateQueries({ queryKey })}
            />
          ) : (
            <ByStudentWorkspace
              students={data.students}
              onUpdated={() => void queryClient.invalidateQueries({ queryKey })}
            />
          )}
        </>
      )}
    </section>
  );
}

function ModeButton({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      className={`min-h-touch rounded-md text-sm font-semibold ${
        active ? "bg-white text-neutral-950 shadow-sm" : "text-neutral-500"
      }`}
    >
      {children}
    </button>
  );
}

function BySkillWorkspace({
  occurrenceId,
  groups,
  students,
  onUpdated,
}: {
  occurrenceId: string;
  groups: CoachSkillGroup[];
  students: CoachSessionSkillsStudent[];
  onUpdated: () => void;
}) {
  const [skillId, setSkillId] = useState(groups[0]?.skill_id ?? "");
  const [status, setStatus] = useState<SkillStatus>("PRACTICING");
  const [selected, setSelected] = useState<string[]>([]);
  const group = groups.find((item) => item.skill_id === skillId) ?? groups[0];
  const sampleSkill = useMemo(
    () => students.flatMap((student) => student.skills).find((skill) => skill.skill_id === group?.skill_id),
    [group?.skill_id, students],
  );

  const mutation = useMutation({
    mutationFn: () =>
      bulkUpdateCoachSessionSkillStatus(occurrenceId, {
        skill_id: group.skill_id,
        program_id: sampleSkill?.program_id ?? "",
        level_id: sampleSkill?.level_id ?? "",
        student_ids: selected.length > 0 ? selected : group.student_ids,
        status,
      }),
    onSuccess: onUpdated,
  });

  if (!group) {
    return <p className="text-sm text-neutral-500">No grouped skill gaps for this session.</p>;
  }

  return (
    <div className="space-y-3 rounded-lg border border-neutral-200 bg-white p-3">
      <label className="block text-sm font-medium text-neutral-600">
        Skill
        <select
          value={group.skill_id}
          onChange={(event) => {
            setSkillId(event.target.value);
            setSelected([]);
          }}
          className="mt-1 min-h-touch w-full rounded-md border border-neutral-300 bg-white px-3"
        >
          {groups.map((item) => (
            <option key={item.skill_id} value={item.skill_id}>
              {item.skill_name}
            </option>
          ))}
        </select>
      </label>

      <div className="space-y-2">
        {group.student_ids.map((studentId, index) => (
          <label key={studentId} className="flex min-h-touch items-center gap-3 text-sm">
            <input
              type="checkbox"
              checked={selected.length === 0 || selected.includes(studentId)}
              onChange={(event) => {
                const base = selected.length === 0 ? group.student_ids : selected;
                setSelected(
                  event.target.checked
                    ? Array.from(new Set([...base, studentId]))
                    : base.filter((item) => item !== studentId),
                );
              }}
            />
            {group.student_names[index] ?? studentId}
          </label>
        ))}
      </div>

      <label className="block text-sm font-medium text-neutral-600">
        New status
        <select
          value={status}
          onChange={(event) => setStatus(event.target.value as SkillStatus)}
          className="mt-1 min-h-touch w-full rounded-md border border-neutral-300 bg-white px-3"
        >
          {STATUS_OPTIONS.map((option) => (
            <option key={option} value={option}>
              {STATUS_LABELS[option]}
            </option>
          ))}
        </select>
      </label>

      {mutation.isError && (
        <p className="rounded-md bg-red-50 p-2 text-sm text-red-700">
          Couldn&apos;t save skill update. Check your connection and retry.
        </p>
      )}
      {mutation.isSuccess && (
        <p className="rounded-md bg-green-50 p-2 text-sm text-green-700">
          Skill update saved.
        </p>
      )}
      <button
        disabled={mutation.isPending || !sampleSkill?.program_id || !sampleSkill?.level_id}
        onClick={() => mutation.mutate()}
        className="min-h-touch w-full rounded-md bg-blue-600 px-3 text-sm font-semibold text-white disabled:opacity-50"
      >
        {mutation.isPending ? "Saving..." : "Update selected students"}
      </button>
    </div>
  );
}

function ByStudentWorkspace({
  students,
  onUpdated,
}: {
  students: CoachSessionSkillsStudent[];
  onUpdated: () => void;
}) {
  const [studentId, setStudentId] = useState(students[0]?.student_id ?? "");
  const student = students.find((item) => item.student_id === studentId) ?? students[0];

  if (!student) {
    return <p className="text-sm text-neutral-500">No students on roster.</p>;
  }

  return (
    <div className="space-y-3 rounded-lg border border-neutral-200 bg-white p-3">
      <label className="block text-sm font-medium text-neutral-600">
        Student
        <select
          value={student.student_id}
          onChange={(event) => setStudentId(event.target.value)}
          className="mt-1 min-h-touch w-full rounded-md border border-neutral-300 bg-white px-3"
        >
          {students.map((item) => (
            <option key={item.student_id} value={item.student_id}>
              {item.full_name}
            </option>
          ))}
        </select>
      </label>

      <ul className="space-y-2">
        {student.skills.map((skill) => (
          <StudentSkillRow
            key={skill.skill_id}
            studentId={student.student_id}
            skill={skill}
            onUpdated={onUpdated}
          />
        ))}
      </ul>
    </div>
  );
}

function StudentSkillRow({
  studentId,
  skill,
  onUpdated,
}: {
  studentId: string;
  skill: CoachSkillGap;
  onUpdated: () => void;
}) {
  const [status, setStatus] = useState<SkillStatus>(skill.status as SkillStatus);
  const mutation = useMutation({
    mutationFn: () =>
      updateSkillStatus(studentId, skill.skill_id, {
        program_id: skill.program_id ?? "",
        level_id: skill.level_id ?? "",
        status,
      }),
    onSuccess: onUpdated,
  });

  return (
    <li className="rounded-md bg-neutral-50 p-3">
      <p className="text-sm font-semibold text-neutral-900">{skill.skill_name}</p>
      <div className="mt-2 grid gap-2 min-[360px]:grid-cols-[minmax(0,1fr)_auto]">
        <select
          value={status}
          onChange={(event) => setStatus(event.target.value as SkillStatus)}
          className="min-h-touch min-w-0 rounded-md border border-neutral-300 bg-white px-2 text-sm"
        >
          {STATUS_OPTIONS.map((option) => (
            <option key={option} value={option}>
              {STATUS_LABELS[option]}
            </option>
          ))}
        </select>
        <button
          disabled={mutation.isPending || !skill.program_id || !skill.level_id}
          onClick={() => mutation.mutate()}
          className="min-h-touch rounded-md bg-blue-600 px-3 text-sm font-semibold text-white disabled:opacity-50"
        >
          Save
        </button>
      </div>
      {mutation.isError && (
        <p className="mt-2 text-sm text-red-600">Couldn&apos;t save skill update.</p>
      )}
    </li>
  );
}
