"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { createSkillNote, listSkillNotes, type SkillNote } from "@/lib/api/coach";
import type { ApiError } from "@/lib/api/client";
import { queryKeys } from "@/lib/query/keys";
import { Modal } from "@/components/ds/modal";

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
  const queryClient = useQueryClient();
  const notesKey = queryKeys.coach.skillNotes(studentId, skillId);

  const { data, isLoading, isError, error } = useQuery({
    queryKey: notesKey,
    queryFn: () => listSkillNotes(studentId, skillId),
    enabled: open && Boolean(studentId) && Boolean(skillId),
  });

  const addNoteMutation = useMutation({
    mutationFn: () => createSkillNote(studentId, { skill_id: skillId, body: body.trim() }),
    onSuccess: () => {
      setBody("");
      void queryClient.invalidateQueries({ queryKey: notesKey });
    },
  });

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
              .map((note: SkillNote) => (
                <li
                  key={note.note_id}
                  className="rounded-lg border border-neutral-200 bg-white p-2.5 text-sm dark:border-neutral-800 dark:bg-neutral-900"
                >
                  <p className="whitespace-pre-wrap text-neutral-800 dark:text-neutral-100">{note.body}</p>
                  <p className="mt-1 text-[11px] text-neutral-400">{formatTimestamp(note.created_at)}</p>
                </li>
              ))}
          </ul>
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
