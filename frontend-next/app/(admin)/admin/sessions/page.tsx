"use client";

/**
 * Admin sessions list.
 *
 * Default view: table. Optional "Calendar view" toggle dynamically imports
 * FullCalendar (@fullcalendar/react + @fullcalendar/daygrid) to keep the
 * initial JS payload small.
 */

import dynamic from "next/dynamic";
import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import * as Dialog from "@radix-ui/react-dialog";

import {
  listAdminSessions,
  createAdminSession,
  deleteAdminSession,
  type AdminSessionView,
  type CreateSessionRequest,
} from "@/lib/api/admin";
import { queryKeys } from "@/lib/query/keys";

// FullCalendar is only loaded when user explicitly switches to Calendar view.
const AdminCalendarView = dynamic(() => import("@/components/admin/AdminCalendarView"), {
  ssr: false,
  loading: () => (
    <div className="h-96 animate-pulse rounded-lg bg-neutral-100 dark:bg-neutral-800" />
  ),
});

function todayISO(): string {
  return new Date().toISOString().slice(0, 10);
}

function formatTimeRange(start: string, end: string): string {
  const fmt = (s: string) =>
    new Date(s).toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
  return `${fmt(start)} – ${fmt(end)}`;
}

export default function AdminSessionsPage() {
  const [date, setDate] = useState<string>(todayISO());
  const [view, setView] = useState<"table" | "calendar">("table");
  const [createOpen, setCreateOpen] = useState(false);
  const queryClient = useQueryClient();

  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: queryKeys.admin.sessions(date),
    queryFn: () => listAdminSessions(date),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => deleteAdminSession(id),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.admin.sessions(date) });
    },
  });

  const sessions = data?.sessions ?? [];

  return (
    <section data-testid="admin-sessions">
      <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-semibold">Sessions</h1>
        <div className="flex items-center gap-2">
          {/* View toggle */}
          <div className="flex rounded-md border border-neutral-200 dark:border-neutral-700 overflow-hidden">
            <button
              onClick={() => setView("table")}
              className={`px-3 min-h-touch text-sm font-medium transition-colors ${
                view === "table"
                  ? "bg-blue-600 text-white"
                  : "bg-white dark:bg-neutral-900 text-neutral-700 dark:text-neutral-300 hover:bg-neutral-50"
              }`}
            >
              Table
            </button>
            <button
              onClick={() => setView("calendar")}
              className={`px-3 min-h-touch text-sm font-medium transition-colors border-l border-neutral-200 dark:border-neutral-700 ${
                view === "calendar"
                  ? "bg-blue-600 text-white"
                  : "bg-white dark:bg-neutral-900 text-neutral-700 dark:text-neutral-300 hover:bg-neutral-50"
              }`}
            >
              Calendar
            </button>
          </div>
          {/* Create session */}
          <button
            onClick={() => setCreateOpen(true)}
            className="min-h-touch rounded-md bg-blue-600 px-4 text-sm font-medium text-white hover:bg-blue-700"
          >
            + Create session
          </button>
        </div>
      </div>

      {/* Date picker (table view only) */}
      {view === "table" && (
        <div className="mb-4 flex items-center gap-2">
          <label htmlFor="session-date" className="text-sm text-neutral-600 dark:text-neutral-400">
            Date:
          </label>
          <input
            id="session-date"
            type="date"
            value={date}
            onChange={(e) => setDate(e.target.value)}
            className="rounded-md border border-neutral-300 dark:border-neutral-700 bg-white dark:bg-neutral-900 px-3 py-1.5 text-sm"
          />
        </div>
      )}

      {isError && (
        <div
          role="alert"
          className="mb-4 rounded-md border border-red-200 bg-red-50 p-4 text-sm text-red-800 dark:border-red-900 dark:bg-red-950 dark:text-red-200"
        >
          <p>Failed to load sessions.</p>
          <button
            onClick={() => void refetch()}
            className="mt-2 min-h-touch rounded-md border px-3"
          >
            Retry
          </button>
        </div>
      )}

      {view === "calendar" ? (
        <AdminCalendarView sessions={sessions} />
      ) : isLoading ? (
        <TableSkeleton />
      ) : sessions.length === 0 ? (
        <p className="text-neutral-500 text-sm" data-testid="sessions-empty">
          No sessions on {date}.
        </p>
      ) : (
        <SessionTable
          sessions={sessions}
          onDelete={(id) => {
            if (confirm("Cancel this session? This cannot be undone.")) {
              deleteMutation.mutate(id);
            }
          }}
        />
      )}

      <CreateSessionDialog
        open={createOpen}
        onOpenChange={setCreateOpen}
        onCreated={() => {
          setCreateOpen(false);
          void queryClient.invalidateQueries({ queryKey: queryKeys.admin.sessions(date) });
        }}
      />
    </section>
  );
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function SessionTable({
  sessions,
  onDelete,
}: {
  sessions: AdminSessionView[];
  onDelete: (id: string) => void;
}) {
  return (
    <div className="overflow-x-auto rounded-lg border border-neutral-200 dark:border-neutral-800">
      <table className="w-full text-sm bg-white dark:bg-neutral-900">
        <thead>
          <tr className="border-b border-neutral-200 dark:border-neutral-700 text-left text-neutral-500">
            <th className="px-4 py-3 font-medium">Title</th>
            <th className="px-4 py-3 font-medium">Location</th>
            <th className="px-4 py-3 font-medium">Time</th>
            <th className="px-4 py-3 font-medium text-right">Enrolled</th>
            <th className="px-4 py-3 font-medium text-right">Waitlist</th>
            <th className="px-4 py-3 font-medium sr-only">Actions</th>
          </tr>
        </thead>
        <tbody>
          {sessions.map((s) => (
            <tr
              key={s.session_id}
              data-testid={`session-row-${s.session_id}`}
              className="border-b border-neutral-100 dark:border-neutral-800 last:border-0 hover:bg-neutral-50 dark:hover:bg-neutral-800"
            >
              <td className="px-4 py-3">
                <a
                  href={`/admin/sessions/${s.session_id}`}
                  className="font-medium text-blue-600 hover:underline dark:text-blue-400"
                >
                  {s.title}
                </a>
              </td>
              <td className="px-4 py-3 text-neutral-600 dark:text-neutral-400">{s.location}</td>
              <td className="px-4 py-3 tabular-nums text-neutral-600 dark:text-neutral-400">
                {formatTimeRange(s.start_at, s.end_at)}
              </td>
              <td className="px-4 py-3 text-right tabular-nums">
                {s.enrolled_count}/{s.capacity}
              </td>
              <td className="px-4 py-3 text-right tabular-nums">{s.waitlist_count}</td>
              <td className="px-4 py-3 text-right">
                <button
                  onClick={() => onDelete(s.session_id)}
                  className="min-h-touch rounded-md border border-red-200 px-2 text-xs text-red-600 hover:bg-red-50 dark:border-red-800 dark:text-red-400"
                  aria-label={`Cancel session ${s.title}`}
                >
                  Cancel
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function TableSkeleton() {
  return (
    <div className="space-y-2">
      {[0, 1, 2].map((i) => (
        <div
          key={i}
          className="h-14 animate-pulse rounded-lg bg-neutral-100 dark:bg-neutral-800"
        />
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Create session dialog
// ---------------------------------------------------------------------------

const EMPTY_FORM: CreateSessionRequest = {
  coach_id: "",
  title: "",
  location: "",
  start_at: "",
  end_at: "",
  capacity: 10,
};

function CreateSessionDialog({
  open,
  onOpenChange,
  onCreated,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  onCreated: () => void;
}) {
  const [form, setForm] = useState<CreateSessionRequest>(EMPTY_FORM);
  const [error, setError] = useState<string | null>(null);

  const mutation = useMutation({
    mutationFn: (payload: CreateSessionRequest) => createAdminSession(payload),
    onSuccess: () => {
      setForm(EMPTY_FORM);
      setError(null);
      onCreated();
    },
    onError: (err: Error) => {
      setError(err.message ?? "Failed to create session.");
    },
  });

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    mutation.mutate(form);
  };

  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 bg-black/40" />
        <Dialog.Content
          className="fixed left-1/2 top-1/2 z-50 w-full max-w-md -translate-x-1/2 -translate-y-1/2 rounded-xl bg-white dark:bg-neutral-900 p-6 shadow-xl focus:outline-none"
          aria-describedby="create-session-desc"
        >
          <Dialog.Title className="text-lg font-semibold mb-1">Create session</Dialog.Title>
          <Dialog.Description id="create-session-desc" className="text-sm text-neutral-500 mb-4">
            Fill in the details below to schedule a new session.
          </Dialog.Description>

          {error && (
            <p role="alert" className="mb-3 rounded-md bg-red-50 p-2 text-sm text-red-700 dark:bg-red-950 dark:text-red-300">
              {error}
            </p>
          )}

          <form onSubmit={handleSubmit} className="space-y-3">
            <Field label="Coach ID" required>
              <input
                type="text"
                required
                value={form.coach_id}
                onChange={(e) => setForm((f) => ({ ...f, coach_id: e.target.value }))}
                className={inputClass}
                placeholder="uid-…"
              />
            </Field>
            <Field label="Title" required>
              <input
                type="text"
                required
                value={form.title}
                onChange={(e) => setForm((f) => ({ ...f, title: e.target.value }))}
                className={inputClass}
              />
            </Field>
            <Field label="Location" required>
              <input
                type="text"
                required
                value={form.location}
                onChange={(e) => setForm((f) => ({ ...f, location: e.target.value }))}
                className={inputClass}
              />
            </Field>
            <div className="grid grid-cols-2 gap-3">
              <Field label="Start" required>
                <input
                  type="datetime-local"
                  required
                  value={form.start_at}
                  onChange={(e) => setForm((f) => ({ ...f, start_at: e.target.value }))}
                  className={inputClass}
                />
              </Field>
              <Field label="End" required>
                <input
                  type="datetime-local"
                  required
                  value={form.end_at}
                  onChange={(e) => setForm((f) => ({ ...f, end_at: e.target.value }))}
                  className={inputClass}
                />
              </Field>
            </div>
            <Field label="Capacity" required>
              <input
                type="number"
                required
                min={1}
                value={form.capacity}
                onChange={(e) =>
                  setForm((f) => ({ ...f, capacity: parseInt(e.target.value, 10) || 1 }))
                }
                className={inputClass}
              />
            </Field>

            <div className="flex justify-end gap-2 pt-2">
              <Dialog.Close asChild>
                <button
                  type="button"
                  className="min-h-touch rounded-md border border-neutral-300 px-4 text-sm dark:border-neutral-700"
                >
                  Cancel
                </button>
              </Dialog.Close>
              <button
                type="submit"
                disabled={mutation.isPending}
                className="min-h-touch rounded-md bg-blue-600 px-4 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-60"
              >
                {mutation.isPending ? "Creating…" : "Create"}
              </button>
            </div>
          </form>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

const inputClass =
  "w-full rounded-md border border-neutral-300 dark:border-neutral-700 bg-white dark:bg-neutral-900 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500";

function Field({
  label,
  required,
  children,
}: {
  label: string;
  required?: boolean;
  children: React.ReactNode;
}) {
  return (
    <label className="block">
      <span className="mb-1 block text-sm font-medium text-neutral-700 dark:text-neutral-300">
        {label}
        {required && <span aria-hidden="true" className="ml-0.5 text-red-500">*</span>}
      </span>
      {children}
    </label>
  );
}
