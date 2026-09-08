"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  createSkillNote,
  listSkillNotes,
  setSkillNoteVisibility,
  type NoteVisibility,
  type SkillNote,
} from "@/lib/api/coach";
import type { ApiError } from "@/lib/api/client";
import { queryKeys } from "@/lib/query/keys";
import { Modal } from "@/components/ds/modal";
import { canChangeNoteVisibility, useCoachSurface } from "./coach-surface-context";

const BODY_MAX_LENGTH = 1000;

function formatTimestamp(value: string): string {
  return new Date(value).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

export function SkillNotesPanel({
  open,
  onClose,
  studentId,
  skillId,
  skillName,
}: {
  open: boolean;
  onClose: () => void;
  studentId: string;
  skillId: string;
  skillName: string;
}) {
  const [body, setBody] = useState("");
  const [share, setShare] = useState(false);
  const queryClient = useQueryClient();
  const notesKey = queryKeys.coach.skillNotes(studentId, skillId);
  // Assistant coaches write notes but never share them (the BFF 403s a
  // `shared` create and any visibility change), so no share control at all.
  const scope = useCoachSurface();
  const assistant = scope.assistant;

  const { data, isLoading, isError, error } = useQuery({
    queryKey: notesKey,
    queryFn: () => listSkillNotes(studentId, skillId),
    enabled: open && Boolean(studentId) && Boolean(skillId),
  });

  const addNoteMutation = useMutation({
    mutationFn: () =>
      createSkillNote(studentId, {
        skill_id: skillId,
        body: body.trim(),
        visibility: !assistant && share ? "shared" : "private",
      }),
    onSuccess: () => {
      setBody("");
      setShare(false);
      void queryClient.invalidateQueries({ queryKey: notesKey });
    },
  });

  const visibilityMutation = useMutation({
    mutationFn: ({ noteId, visibility }: { noteId: string; visibility: NoteVisibility }) =>
      setSkillNoteVisibility(studentId, noteId, visibility),
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: notesKey });
    },
  });
  const visibilityPendingId = visibilityMutation.isPending
    ? visibilityMutation.variables?.noteId ?? null
    : null;

  const unavailable = (error as ApiError | undefined)?.status === 503;
  const notes = data?.notes ?? [];

  return (
    <Modal open={open} onClose={onClose} title={`Notes — ${skillName}`} size="md">
      <div className="space-y-3">
        {isLoading ? (
          <div className="space-y-2">
            {[0, 1].map((i) => (
              <div key={i} className="h-12 animate-pulse rounded-lg bg-neutral-100 dark:bg-neutral-800" />
            ))}
          </div>
        ) : isError ? (
          <p className="rounded-md bg-neutral-50 p-3 text-xs text-neutral-500 dark:bg-neutral-800">
            {unavailable ? "Notes are currently unavailable." : "Couldn't load notes. Try again."}
          </p>
        ) : notes.length === 0 ? (
          <p className="text-xs text-neutral-500">No notes yet for this skill.</p>
        ) : (
          <ul className="max-h-64 space-y-2 overflow-y-auto">
            {[...notes]
              .sort((a, b) => b.created_at.localeCompare(a.created_at))
              .map((note: SkillNote) => {
                const shared = note.visibility === "shared";
                const pending = visibilityPendingId === note.note_id;
                // The listing carries every author's notes for this skill, but
                // only the author (or a supervisor) can flip one — anyone else
                // gets a 404 from SetSkillNoteVisibility.
                const canChange = canChangeNoteVisibility(scope, note.coach_id);
                return (
                  <li
                    key={note.note_id}
                    data-testid={`skill-note-${note.note_id}`}
                    className="rounded-lg border border-neutral-200 bg-white p-2.5 text-sm dark:border-neutral-800 dark:bg-neutral-900"
                  >
                    <p className="whitespace-pre-wrap text-neutral-800 dark:text-neutral-100">{note.body}</p>
                    <div className="mt-1.5 flex flex-wrap items-center justify-between gap-2">
                      <span className="flex items-center gap-2">
                        <span
                          data-testid={`skill-note-visibility-${note.note_id}`}
                          className={`inline-flex items-center rounded px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide ${
                            shared
                              ? "bg-green-50 text-green-800"
                              : "bg-neutral-100 text-neutral-600 dark:bg-neutral-800 dark:text-neutral-300"
                          }`}
                        >
                          {shared ? "Shared" : "Private"}
                        </span>
                        <span className="text-[11px] text-neutral-400">
                          {formatTimestamp(note.created_at)}
                        </span>
                      </span>
                      {canChange && (
                        <button
                          data-testid={`skill-note-share-toggle-${note.note_id}`}
                          disabled={pending}
                          onClick={() =>
                            visibilityMutation.mutate({
                              noteId: note.note_id,
                              visibility: shared ? "private" : "shared",
                            })
                          }
                          className="min-h-touch rounded-lg border border-neutral-300 px-3 text-xs font-medium text-neutral-700 disabled:opacity-50 dark:border-neutral-700 dark:text-neutral-300"
                        >
                          {pending ? "Saving..." : shared ? "Make private" : "Share"}
                        </button>
                      )}
                    </div>
                  </li>
                );
              })}
          </ul>
        )}
        {visibilityMutation.isError && (
          <p className="text-xs text-red-600">Couldn&apos;t change who sees that note. Try again.</p>
        )}

        {!unavailable && (
          <div className="space-y-2 border-t border-neutral-200 pt-3 dark:border-neutral-800">
            <textarea
              value={body}
              onChange={(e) => setBody(e.target.value.slice(0, BODY_MAX_LENGTH))}
              placeholder="Add a note about this skill..."
              rows={3}
              maxLength={BODY_MAX_LENGTH}
              className="w-full rounded-md border border-neutral-300 px-2 py-1.5 text-sm focus:border-blue-500 focus:outline-none dark:border-neutral-700 dark:bg-neutral-800"
            />
            {assistant ? (
              <p data-testid="skill-note-private-hint" className="text-xs text-neutral-500">
                Notes you write stay private to coaches.
              </p>
            ) : (
              // "Mark as shared", not "Share with parent": nothing on the
              // parent side reads coach_skill_notes yet (the parent feed reads
              // progress_notes + session_feedback, and parent skill updates
              // come from student_progress). The flag is real and enforced —
              // it just isn't a parent-visible surface today.
              <div className="space-y-1">
                <label className="flex min-h-touch items-center gap-2 text-sm text-neutral-700 dark:text-neutral-300">
                  <input
                    type="checkbox"
                    data-testid="skill-note-share"
                    checked={share}
                    onChange={(e) => setShare(e.target.checked)}
                    className="h-5 w-5 rounded border-neutral-300"
                  />
                  Mark as shared
                </label>
                <p data-testid="skill-note-share-hint" className="text-xs text-neutral-500">
                  Shared skill notes are not in the parent portal yet.
                </p>
              </div>
            )}
            <div className="flex items-center justify-between">
              <span className="text-[11px] text-neutral-400">
                {body.length}/{BODY_MAX_LENGTH}
              </span>
              <button
                disabled={!body.trim() || addNoteMutation.isPending}
                onClick={() => addNoteMutation.mutate()}
                className="min-h-touch rounded-lg bg-blue-600 px-4 py-2 text-sm font-semibold text-white transition-all active:scale-95 disabled:cursor-not-allowed disabled:opacity-40"
              >
                {addNoteMutation.isPending ? "Adding..." : "Add Note"}
              </button>
            </div>
            {addNoteMutation.isError && (
              <p className="text-xs text-red-600">Failed to add note. Try again.</p>
            )}
          </div>
        )}
      </div>
    </Modal>
  );
}
