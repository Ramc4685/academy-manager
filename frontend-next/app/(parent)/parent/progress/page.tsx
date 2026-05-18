"use client";

import { useQuery } from "@tanstack/react-query";

import { listParentProgress } from "@/lib/api/parent";

export default function ParentProgressPage() {
  const { data, isLoading, isError } = useQuery({
    queryKey: ["parent", "progress"],
    queryFn: listParentProgress,
  });

  const notes = data?.notes ?? [];

  return (
    <section data-testid="parent-progress">
      <h1 className="mb-4 text-2xl font-semibold">Progress</h1>
      {isError ? (
        <p className="text-sm text-red-600">Could not load progress notes.</p>
      ) : isLoading ? (
        <p className="text-sm text-neutral-500">Loading…</p>
      ) : notes.length === 0 ? (
        <p className="text-sm text-neutral-500">No progress notes yet.</p>
      ) : (
        <ul className="space-y-3">
          {notes.map((note) => (
            <li key={note.note_id} className="rounded-lg border border-neutral-200 bg-white p-4 dark:border-neutral-800 dark:bg-neutral-900">
              <div className="mb-2 flex items-center justify-between gap-3">
                <p className="font-medium">{note.student_name}</p>
                <p className="text-xs text-neutral-500">{new Date(note.created_at).toLocaleDateString()}</p>
              </div>
              <p className="text-sm leading-6 text-neutral-700 dark:text-neutral-300">{note.body}</p>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
