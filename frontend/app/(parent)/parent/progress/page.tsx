"use client";

import { Suspense, useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { Skeleton } from "@/components/ds/skeleton";
import { EmptyState } from "@/components/ds/empty-state";
import { ErrorNotice } from "@/components/ds/error-notice";
import {
  listParentProgress,
  listParentChildren,
  getParentProgressJourney,
} from "@/lib/api/parent";
import { getParentStudentCertificates } from "@/lib/api/curriculum";
import { queryKeys } from "@/lib/query/keys";
import {
  CertificateList,
  JourneySkeleton,
  LevelRing,
  LevelStrip,
  PracticeDrillCard,
  RecentWins,
  SkillChecklist,
} from "./journey";

// Per-note left-border accents are derived from the note id hash — genuinely
// dynamic, so these stay as literal color stops (no single token pair
// covers a rotating 6-way palette). Mirrors the per-child avatar gradient
// exception in children/page.tsx.
// #843: the purple and pink stops were the only colours here with no token
// behind them; the rotation is now Rally cobalt / slate plus DS status hues.
const ACCENTS = ["#2563eb", "#059669", "#475569", "#d97706", "#0891b2", "#1e3a8a"];
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
      <h1 className="sr-only">Progress</h1>

      {/* The evening win email lands here, so the journey leads. */}
      <Suspense fallback={null}>
        <SkillProgressSection />
      </Suspense>

      <div className="mt-8 mb-4">
        <h2 className="font-display text-xl font-bold tracking-tight text-rally-ink">
          Notes from coaches
        </h2>
      </div>

      {isError ? (
        <p className="text-sm text-status-red-600">Could not load progress notes.</p>
      ) : isLoading ? (
        <NotesSkeleton />
      ) : notes.length === 0 ? (
        <EmptyNotes />
      ) : (
        <NotesList notes={notes as NoteEntry[]} />
      )}
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
        <div key={i} className="rounded-2xl p-4 bg-white border border-rally-line">
          <div className="flex gap-3">
            <Skeleton variant="circle" width="2.25rem" height="2.25rem" className="shrink-0" />
            <div className="flex-1 space-y-2">
              <Skeleton variant="line" width="7rem" />
              <Skeleton variant="line" />
              <Skeleton variant="line" width="75%" />
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}

function EmptyNotes() {
  return (
    <div className="rounded-2xl p-10 bg-white border border-rally-line animate-fade-in-up">
      <EmptyState
        title="No progress notes yet"
        description="Notes from coaches will appear here"
      />
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
            className="rounded-2xl overflow-hidden bg-white border border-rally-line animate-fade-in-up transition-all duration-200 hover:-translate-y-0.5 hover:shadow-md"
            style={{ borderLeft: `3px solid ${accent}` }}
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
                    <p className="text-sm font-bold truncate text-rally-ink">
                      {note.student_name}
                    </p>
                    <time className="text-[11px] shrink-0 text-rally-subtle">
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

              <p className="text-sm leading-relaxed text-rally-muted">
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
 * Skill journey — "how far along" for the selected child
 * ---------------------------------------------------------------------- */

function SkillProgressSection() {
  const { data: childrenData } = useQuery({
    queryKey: queryKeys.parent.children(),
    queryFn: listParentChildren,
  });

  const children = useMemo(() => childrenData?.children ?? [], [childrenData]);

  // Home's child cards and the evening win email deep-link here as
  // /parent/progress?child=<student_id>. The param only seeds the selection —
  // the tabs stay the source of truth afterwards, and an absent or unknown id
  // falls back to the first child.
  const requestedChildId = useSearchParams().get("child");
  const [activeChildIdx, setActiveChildIdx] = useState(0);
  // Seed once, after the roster arrives: re-applying it on every render would
  // yank the parent back to the deep-linked child whenever they tap a tab.
  const seededFromQuery = useRef(false);
  const sectionRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (seededFromQuery.current || children.length === 0) return;
    seededFromQuery.current = true;
    if (!requestedChildId) return;
    const idx = children.findIndex((child) => child.student_id === requestedChildId);
    if (idx < 0) return;
    setActiveChildIdx(idx);
    // The roster query is still in flight when the router commits the
    // navigation, so move focus once the child actually resolves.
    sectionRef.current?.focus({ preventScroll: true });
  }, [requestedChildId, children]);

  const activeChild = children[activeChildIdx];
  if (!activeChild) return null;

  return (
    <div
      id="skill-progress"
      ref={sectionRef}
      tabIndex={-1}
      className="space-y-4 animate-fade-in-up outline-none"
    >
      {children.length > 1 && (
        <div className="flex gap-2 flex-wrap" role="tablist" aria-label="Choose a child">
          {children.map((child, idx) => (
            <button
              key={child.student_id}
              type="button"
              role="tab"
              aria-selected={idx === activeChildIdx}
              onClick={() => setActiveChildIdx(idx)}
              className={`rounded-full px-3 min-h-[44px] text-sm font-semibold transition-all ${
                idx === activeChildIdx
                  ? "bg-rally-cobalt-600 text-white"
                  : "bg-rally-cobalt-50 text-rally-cobalt-600"
              }`}
            >
              {child.full_name}
            </button>
          ))}
        </div>
      )}

      <ChildJourney
        key={activeChild.student_id}
        studentId={activeChild.student_id}
        childName={activeChild.full_name}
      />
    </div>
  );
}

function ChildJourney({ studentId, childName }: { studentId: string; childName: string }) {
  const journeyQuery = useQuery({
    queryKey: queryKeys.parent.progressJourney(studentId),
    queryFn: () => getParentProgressJourney(studentId),
  });
  const { data: certs } = useQuery({
    queryKey: ["parent", "certificates", studentId],
    queryFn: () => getParentStudentCertificates(studentId),
  });
  const firstName = childName.split(" ")[0] || childName;

  if (journeyQuery.isLoading) return <JourneySkeleton />;
  if (journeyQuery.isError || !journeyQuery.data) {
    return (
      <ErrorNotice
        message={`Could not load ${firstName}'s progress.`}
        onRetry={() => void journeyQuery.refetch()}
        retrying={journeyQuery.isFetching}
      />
    );
  }

  const journey = journeyQuery.data;
  const current = journey.current_level;

  return (
    <div className="space-y-4" data-testid="parent-progress-journey">
      {current ? (
        <>
          <LevelStrip firstName={firstName} journey={journey} />
          <LevelRing current={current} />
          <SkillChecklist skills={journey.skills} />
        </>
      ) : (
        <div className="rounded-2xl p-4 bg-white border border-rally-line">
          <p className="text-sm font-bold text-rally-ink">{firstName}&apos;s badminton journey</p>
          <p className="mt-1 text-sm text-rally-muted">
            {firstName} hasn&apos;t been placed in a level yet. Their coach places them after
            the first classes, and their skills will show up here.
          </p>
        </div>
      )}
      <RecentWins wins={journey.recent_wins} />
      {journey.practice_drill && <PracticeDrillCard drill={journey.practice_drill} />}
      {certs && certs.length > 0 && <CertificateList certs={certs} />}
    </div>
  );
}
