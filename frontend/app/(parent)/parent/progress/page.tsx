"use client";

import { useQuery } from "@tanstack/react-query";
import { listParentProgress } from "@/lib/api/parent";

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
        <div className="space-y-3">
          {[1, 2, 3].map((i) => (
            <div key={i} className="rounded-2xl p-4" style={{ background: "white", border: "1px solid var(--rally-line)" }}>
              <div className="flex gap-3">
                <div className="h-9 w-9 rounded-xl shimmer shrink-0" />
                <div className="flex-1 space-y-2">
                  <div className="h-3 w-28 rounded shimmer" />
                  <div className="h-3 w-full rounded shimmer" />
                  <div className="h-3 w-3/4 rounded shimmer" />
                </div>
              </div>
            </div>
          ))}
        </div>
      ) : notes.length === 0 ? (
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
      ) : (
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
      )}
    </section>
  );
}
