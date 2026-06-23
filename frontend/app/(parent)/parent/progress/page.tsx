"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  listParentProgress,
  listParentChildren,
  listSkillUpdates,
  listPracticeResources,
  type ParentPracticeResource,
  type ParentSkillUpdate,
} from "@/lib/api/parent";
import {
  getParentStudentPassport,
  getParentStudentCertificates,
  getParentProgressSummary,
  type SkillPassportEntry,
  type SkillCertificate,
  type SkillStatus,
  type StudentProgressOverview,
} from "@/lib/api/curriculum";

const progressOverviewEnabled = process.env.NEXT_PUBLIC_SKILL_PROGRESS_OVERVIEW === "1";

const ACCENTS = ["#2563eb", "#059669", "#7c3aed", "#d97706", "#0891b2", "#db2777"];
function noteAccent(id: string) {
  let h = 0;
  for (let i = 0; i < id.length; i++) h = (h * 31 + id.charCodeAt(i)) & 0xffffffff;
  return ACCENTS[Math.abs(h) % ACCENTS.length];
}

export default function ParentProgressPage() {
  const { data, isLoading, isError } = useQuery({
    queryKey: ["parent", "progress"],
    queryFn: listParentProgress,
  });

  const notes = data?.notes ?? [];

  return (
    <section data-testid="parent-progress">
      <div className="mb-4 animate-fade-in-up">
        <h1 className="font-display text-2xl font-bold tracking-tight" style={{ color: "var(--rally-ink)" }}>
          Progress
        </h1>
        <p className="text-sm mt-0.5" style={{ color: "var(--rally-muted)" }}>
          Notes and feedback from coaches
        </p>
      </div>

      {isError ? (
        <p className="text-sm" style={{ color: "#dc2626" }}>Could not load progress notes.</p>
      ) : isLoading ? (
        <NotesSkeleton />
      ) : notes.length === 0 ? (
        <EmptyNotes />
      ) : (
        <NotesList notes={notes as NoteEntry[]} />
      )}

      {/* Skill Progress section */}
      <SkillProgressSection />
    </section>
  );
}

/* -------------------------------------------------------------------------
 * Extracted sub-components for existing coach-notes UI
 * ---------------------------------------------------------------------- */

function NotesSkeleton() {
  return (
    <div className="space-y-3">
      {[1, 2, 3].map((i) => (
        <div key={i} className="rounded-2xl p-4" style={{ background: "white", border: "1px solid var(--rally-line)" }}>
          <div className="flex gap-3">
            <div className="h-9 w-9 rounded-xl shrink-0 shimmer" />
            <div className="flex-1 space-y-2">
              <div className="h-3 w-28 rounded shimmer" />
              <div className="h-3 w-full rounded shimmer" />
              <div className="h-3 w-3/4 rounded shimmer" />
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}

function EmptyNotes() {
  return (
    <div className="rounded-2xl p-10 text-center animate-fade-in-up" style={{ background: "white", border: "1px solid var(--rally-line)" }}>
      <div
        className="h-12 w-12 rounded-2xl mx-auto flex items-center justify-center mb-3"
        style={{ background: "var(--rally-cobalt-soft)" }}
      >
        <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="var(--rally-cobalt)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <polyline points="22 12 18 12 15 21 9 3 6 12 2 12" />
        </svg>
      </div>
      <p className="font-semibold text-sm" style={{ color: "var(--rally-ink)" }}>No progress notes yet</p>
      <p className="text-xs mt-1" style={{ color: "var(--rally-muted)" }}>Notes from coaches will appear here</p>
    </div>
  );
}

interface NoteEntry {
  note_id: string;
  coach_name: string | null;
  student_name: string;
  created_at: string;
  session_title?: string | null;
  body: string;
}

function NotesList({ notes }: { notes: NoteEntry[] }) {
  return (
    <ul className="space-y-3 stagger-children">
      {notes.map((note) => {
        const accent = noteAccent(note.note_id);
        return (
          <li
            key={note.note_id}
            className="rounded-2xl overflow-hidden animate-fade-in-up transition-all duration-200 hover:-translate-y-0.5 hover:shadow-md"
            style={{ background: "white", border: "1px solid var(--rally-line)", borderLeft: `3px solid ${accent}` }}
          >
            <div className="p-4">
              <div className="flex items-start gap-3 mb-2.5">
                <div
                  className="h-9 w-9 rounded-xl flex items-center justify-center text-sm font-bold text-white shrink-0"
                  style={{ background: accent }}
                >
                  {note.coach_name ? note.coach_name[0].toUpperCase() : "C"}
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center justify-between gap-2">
                    <p className="text-sm font-bold truncate" style={{ color: "var(--rally-ink)" }}>
                      {note.student_name}
                    </p>
                    <time className="text-[11px] shrink-0" style={{ color: "var(--rally-subtle)" }}>
                      {new Date(note.created_at).toLocaleDateString(undefined, { month: "short", day: "numeric" })}
                    </time>
                  </div>
                  {note.coach_name && (
                    <p className="text-xs mt-0.5 font-semibold" style={{ color: accent }}>
                      {note.coach_name}
                    </p>
                  )}
                </div>
              </div>

              {note.session_title && (
                <div className="mb-2">
                  <span
                    className="inline-flex items-center gap-1 text-[11px] font-semibold px-2 py-0.5 rounded-full"
                    style={{ background: `${accent}18`, color: accent }}
                  >
                    <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                      <rect x="3" y="4" width="18" height="18" rx="2" /><line x1="16" y1="2" x2="16" y2="6" /><line x1="8" y1="2" x2="8" y2="6" /><line x1="3" y1="10" x2="21" y2="10" />
                    </svg>
                    {note.session_title}
                  </span>
                </div>
              )}

              <p className="text-sm leading-relaxed" style={{ color: "var(--rally-muted)" }}>
                {note.body}
              </p>
            </div>
          </li>
        );
      })}
    </ul>
  );
}

/* -------------------------------------------------------------------------
 * Skill Progress section — new feature
 * ---------------------------------------------------------------------- */

const SKILL_STATUS_FRIENDLY: Record<SkillStatus, string> = {
  NOT_STARTED: "Not started",
  INTRODUCED: "Introduced",
  LEARNING: "Learning",
  PRACTICING: "Practicing",
  TEST_READY: "Almost there",
  PASSED: "Mastered",
  NEEDS_REVIEW: "Needs review",
};

function skillStatusStyle(status: SkillStatus): { background: string; color: string } {
  switch (status) {
    case "PASSED":
      return { background: "#dcfce7", color: "#15803d" };
    case "TEST_READY":
      return { background: "#dbeafe", color: "#1d4ed8" };
    case "LEARNING":
    case "PRACTICING":
      return { background: "#fef9c3", color: "#a16207" };
    case "NEEDS_REVIEW":
      return { background: "#fee2e2", color: "#b91c1c" };
    default:
      return { background: "#f3f4f6", color: "#6b7280" };
  }
}

function SkillProgressSection() {
  const { data: childrenData } = useQuery({
    queryKey: ["parent", "children"],
    queryFn: listParentChildren,
  });

  const children = childrenData?.children ?? [];

  const [activeChildIdx, setActiveChildIdx] = useState(0);

  const activeChild = children[activeChildIdx];
  const { data: overviewRows, isLoading: loadingOverview } = useQuery({
    queryKey: ["parent", "progress-summary", "default"],
    queryFn: () => getParentProgressSummary(),
    enabled: progressOverviewEnabled,
  });
  const activeChildOverview =
    activeChild && overviewRows
      ? overviewRows.find((row) => row.student_id === activeChild.student_id)
      : undefined;

  if (children.length === 0) return null;

  return (
    <div className="mt-8 space-y-4 animate-fade-in-up">
      {/* Section heading */}
      <div>
        <h2 className="font-display text-xl font-bold tracking-tight" style={{ color: "var(--rally-ink)" }}>
          Skill Progress
        </h2>
        <p className="text-sm mt-0.5" style={{ color: "var(--rally-muted)" }}>
          Level and skills overview for each child
        </p>
      </div>

      {/* Child tabs */}
      {children.length > 1 && (
        <div className="flex gap-2 flex-wrap">
          {children.map((child, idx) => (
            <button
              key={child.student_id}
              onClick={() => setActiveChildIdx(idx)}
              className="rounded-full px-3 py-1.5 text-sm font-semibold transition-all"
              style={
                idx === activeChildIdx
                  ? { background: "var(--rally-cobalt)", color: "white" }
                  : { background: "var(--rally-cobalt-soft)", color: "var(--rally-cobalt)" }
              }
            >
              {child.full_name}
            </button>
          ))}
        </div>
      )}

      {activeChild && (
        <>
          {progressOverviewEnabled && (
            <ParentProgressSummaryCard
              overview={activeChildOverview}
              isLoading={loadingOverview}
              childName={activeChild.full_name}
            />
          )}
          <ChildPassportView
            studentId={activeChild.student_id}
            studentName={activeChild.full_name}
          />
        </>
      )}
    </div>
  );
}

function ParentProgressSummaryCard({
  overview,
  isLoading,
  childName,
}: {
  overview: StudentProgressOverview | undefined;
  isLoading: boolean;
  childName: string;
}) {
  if (isLoading) {
    return <div className="h-28 animate-pulse rounded-2xl shimmer" />;
  }

  if (!overview) {
    return (
      <div
        className="rounded-2xl p-4"
        style={{ background: "white", border: "1px solid var(--rally-line)" }}
      >
        <p className="text-sm font-bold" style={{ color: "var(--rally-ink)" }}>
          {childName}
        </p>
        <p className="mt-1 text-sm" style={{ color: "var(--rally-muted)" }}>
          No level placement found for this program.
        </p>
      </div>
    );
  }

  const totalPct =
    overview.total_skill_count > 0
      ? Math.round((overview.total_skills_passed / overview.total_skill_count) * 100)
      : 0;

  return (
    <div
      className="rounded-2xl p-4"
      style={{ background: "white", border: "1px solid var(--rally-line)" }}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-sm font-bold truncate" style={{ color: "var(--rally-ink)" }}>
            {overview.student_name}
          </p>
          <p className="mt-0.5 text-xs truncate" style={{ color: "var(--rally-muted)" }}>
            {overview.current_level_name ?? "Not placed"} · {overview.program_name}
          </p>
        </div>
        <span
          className="shrink-0 rounded-full px-2 py-0.5 text-xs font-semibold"
          style={{ background: "var(--rally-cobalt-soft)", color: "var(--rally-cobalt)" }}
        >
          {totalPct}%
        </span>
      </div>
      <div className="mt-3 h-2 overflow-hidden rounded-full" style={{ background: "var(--rally-line)" }}>
        <div
          className="h-full rounded-full transition-all duration-500"
          style={{ width: `${totalPct}%`, background: "var(--rally-cobalt)" }}
        />
      </div>
      <div className="mt-3 grid grid-cols-3 gap-2 text-center">
        <SummaryMetric label="Mastered" value={overview.total_skills_passed} />
        <SummaryMetric label="Learning" value={overview.in_progress_count} />
        <SummaryMetric label="Ready" value={overview.test_ready_count} />
      </div>
    </div>
  );
}

function SummaryMetric({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-xl px-2 py-2" style={{ background: "#f8fafc" }}>
      <p className="text-sm font-bold" style={{ color: "var(--rally-ink)" }}>
        {value}
      </p>
      <p className="text-[11px]" style={{ color: "var(--rally-muted)" }}>
        {label}
      </p>
    </div>
  );
}

function ChildPassportView({
  studentId,
  studentName,
}: {
  studentId: string;
  studentName: string;
}) {
  const { data: passport, isLoading: loadingPassport } = useQuery({
    queryKey: ["parent", "passport", studentId, "default"],
    queryFn: () => getParentStudentPassport(studentId),
    enabled: Boolean(studentId),
  });

  const { data: certs, isLoading: loadingCerts } = useQuery({
    queryKey: ["parent", "certificates", studentId],
    queryFn: () => getParentStudentCertificates(studentId),
    enabled: Boolean(studentId),
  });

  const { data: updates, isLoading: loadingUpdates } = useQuery({
    queryKey: ["parent", "skill-updates", studentId],
    queryFn: () => listSkillUpdates(studentId),
    enabled: Boolean(studentId),
  });

  const { data: practiceResources, isLoading: loadingPracticeResources } = useQuery({
    queryKey: ["parent", "practice-resources", studentId],
    queryFn: () => listPracticeResources(studentId),
    enabled: Boolean(studentId),
  });

  const skills = passport ?? [];
  const certList = certs ?? [];
  const passedCount = skills.filter((s) => s.status === "PASSED").length;

  return (
    <div className="space-y-4">
      {/* Summary card */}
      {skills.length > 0 && (
        <div
          className="rounded-2xl p-4"
          style={{ background: "white", border: "1px solid var(--rally-line)" }}
        >
          <div className="flex items-center justify-between mb-3">
            <p className="text-sm font-bold" style={{ color: "var(--rally-ink)" }}>
              {studentName}
            </p>
            <span
              className="text-xs font-semibold px-2 py-0.5 rounded-full"
              style={{ background: "var(--rally-cobalt-soft)", color: "var(--rally-cobalt)" }}
            >
              {passedCount}/{skills.length} mastered
            </span>
          </div>
          <div className="h-2 rounded-full overflow-hidden" style={{ background: "var(--rally-line)" }}>
            <div
              className="h-full rounded-full transition-all duration-500"
              style={{
                width: skills.length > 0 ? `${Math.round((passedCount / skills.length) * 100)}%` : "0%",
                background: "var(--rally-cobalt)",
              }}
            />
          </div>
        </div>
      )}

      <RecentSkillUpdatesTimeline updates={updates ?? []} isLoading={loadingUpdates} />

      {/* Skill list */}
      {loadingPassport ? (
        <SkillListSkeleton />
      ) : skills.length === 0 ? (
        <p className="text-sm" style={{ color: "var(--rally-muted)" }}>
          No skills found for this program.
        </p>
      ) : (
        <ul className="space-y-2 stagger-children">
          {skills.map((entry) => (
            <SkillItem key={entry.skill_id} entry={entry} />
          ))}
        </ul>
      )}

      <PracticeResourcesCard
        resources={practiceResources ?? []}
        isLoading={loadingPracticeResources}
      />

      {/* Certificates */}
      {!loadingCerts && certList.length > 0 && (
        <div
          className="rounded-2xl overflow-hidden animate-fade-in-up"
          style={{ background: "white", border: "1px solid var(--rally-line)" }}
        >
          <div
            className="px-4 py-3"
            style={{ background: "linear-gradient(135deg,#0a0f1c 0%,#0f1d38 100%)" }}
          >
            <p className="text-[10px] font-bold uppercase tracking-widest text-white/50">
              Certificates
            </p>
          </div>
          <ul className="divide-y" style={{ borderColor: "var(--rally-line)" }}>
            {certList.map((cert) => (
              <CertificateItem key={cert.cert_id} cert={cert} />
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function RecentSkillUpdatesTimeline({
  updates,
  isLoading,
}: {
  updates: ParentSkillUpdate[];
  isLoading: boolean;
}) {
  if (isLoading) {
    return <div className="h-28 animate-pulse rounded-2xl shimmer" />;
  }

  if (updates.length === 0) return null;

  return (
    <div
      className="rounded-2xl overflow-hidden animate-fade-in-up"
      style={{ background: "white", border: "1px solid var(--rally-line)" }}
    >
      <div className="px-4 py-3" style={{ borderBottom: "1px solid var(--rally-line)" }}>
        <p className="text-sm font-bold" style={{ color: "var(--rally-ink)" }}>
          Recent skill updates
        </p>
      </div>
      <ol className="divide-y" style={{ borderColor: "var(--rally-line)" }}>
        {updates.map((update) => (
          <li key={`${update.skill_id}-${update.updated_at}`} className="flex gap-3 px-4 py-3">
            <time
              className="w-14 shrink-0 text-xs font-semibold"
              style={{ color: "var(--rally-subtle)" }}
            >
              {formatUpdateDate(update.updated_at)}
            </time>
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-semibold" style={{ color: "var(--rally-ink)" }}>
                {update.skill_name}
              </p>
            </div>
            <SkillStatusChip status={update.status} />
          </li>
        ))}
      </ol>
    </div>
  );
}

function SkillItem({ entry }: { entry: SkillPassportEntry }) {
  const label = SKILL_STATUS_FRIENDLY[entry.status];
  const checkmark = entry.status === "PASSED";
  const style = skillStatusStyle(entry.status);

  return (
    <li
      className="flex items-center gap-3 rounded-xl px-3 py-2.5 animate-fade-in-up"
      style={{ background: "white", border: "1px solid var(--rally-line)" }}
    >
      <div
        className="h-7 w-7 rounded-lg flex items-center justify-center shrink-0 text-sm"
        style={{ background: style.background, color: style.color }}
      >
        {checkmark ? "✓" : entry.sequence}
      </div>
      <div className="flex-1 min-w-0">
        <p className="text-sm font-medium truncate" style={{ color: "var(--rally-ink)" }}>
          {entry.skill_name}
        </p>
      </div>
      <SkillStatusChip status={entry.status} label={label} />
    </li>
  );
}

function SkillStatusChip({
  status,
  label = SKILL_STATUS_FRIENDLY[status],
}: {
  status: SkillStatus;
  label?: string;
}) {
  return (
    <span
      className="shrink-0 text-[11px] font-semibold px-2 py-0.5 rounded-full"
      style={skillStatusStyle(status)}
    >
      {label}
    </span>
  );
}

function PracticeResourcesCard({
  resources,
  isLoading,
}: {
  resources: ParentPracticeResource[];
  isLoading: boolean;
}) {
  if (isLoading) {
    return <div className="h-24 animate-pulse rounded-2xl shimmer" />;
  }

  if (resources.length === 0) return null;

  return (
    <div
      className="rounded-2xl overflow-hidden animate-fade-in-up"
      style={{ background: "white", border: "1px solid var(--rally-line)" }}
    >
      <div className="px-4 py-3" style={{ borderBottom: "1px solid var(--rally-line)" }}>
        <p className="text-sm font-bold" style={{ color: "var(--rally-ink)" }}>
          Practice at home
        </p>
      </div>
      <ul className="divide-y" style={{ borderColor: "var(--rally-line)" }}>
        {resources.map((resource) => (
          <li key={resource.skill_id} className="px-4 py-3">
            <p className="text-sm font-semibold" style={{ color: "var(--rally-ink)" }}>
              {resource.skill_name}
            </p>
            <div className="mt-2 flex flex-wrap gap-2">
              {resource.resource_links.map((link) => (
                <a
                  key={`${resource.skill_id}-${link.url}`}
                  href={link.url}
                  target="_blank"
                  rel="noreferrer"
                  className="inline-flex max-w-full items-center gap-1 rounded-full px-2.5 py-1 text-xs font-semibold transition-all hover:-translate-y-0.5"
                  style={{ background: "var(--rally-cobalt-soft)", color: "var(--rally-cobalt)" }}
                >
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
                    <path d="M8 5v14l11-7z" />
                  </svg>
                  <span className="truncate">{link.title}</span>
                </a>
              ))}
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}

function CertificateItem({ cert }: { cert: SkillCertificate }) {
  return (
    <li className="flex items-center gap-3 px-4 py-3">
      <div
        className="h-8 w-8 rounded-lg flex items-center justify-center shrink-0 text-lg"
        style={{ background: "#fef9c3" }}
      >
        🏅
      </div>
      <div className="flex-1 min-w-0">
        <p className="text-sm font-semibold truncate" style={{ color: "var(--rally-ink)" }}>
          {cert.level_name}
        </p>
        <p className="text-xs truncate" style={{ color: "var(--rally-muted)" }}>
          {cert.program_name}
        </p>
      </div>
      <div className="shrink-0 text-right">
        <p className="text-xs font-medium" style={{ color: "var(--rally-ink)" }}>
          {new Date(cert.completed_at).toLocaleDateString(undefined, {
            month: "short",
            day: "numeric",
            year: "numeric",
          })}
        </p>
        <p className="text-[11px]" style={{ color: "var(--rally-subtle)" }}>
          #{cert.cert_number}
        </p>
      </div>
    </li>
  );
}

function SkillListSkeleton() {
  return (
    <div className="space-y-2">
      {[0, 1, 2, 3].map((i) => (
        <div key={i} className="h-11 animate-pulse rounded-xl shimmer" />
      ))}
    </div>
  );
}

function formatUpdateDate(value: string) {
  return new Date(value).toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
  });
}
