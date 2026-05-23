"use client";

/**
 * Admin sessions list — Rally restyle.
 *
 * Preserves: table/calendar view toggle, date filter, create dialog,
 * cancel-with-confirm. Calendar still dynamic-imported.
 *
 * Backend gap: AdminSessionView may have coach_id without coach_name.
 * Normal admin UI intentionally avoids rendering raw coach references.
 */

import dynamic from "next/dynamic";
import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import * as Dialog from "@radix-ui/react-dialog";

import {
  listAdminSessions,
  listAdminUsers,
  createAdminSession,
  deleteAdminSession,
  type AdminUserView,
  type AdminSessionView,
  type CreateSessionRequest,
} from "@/lib/api/admin";
import { queryKeys } from "@/lib/query/keys";

import { Avatar } from "@/components/ds/avatar";
import { Button } from "@/components/ds/button";
import { Card } from "@/components/ds/card";
import { Chip, type ChipVariant } from "@/components/ds/chip";
import { Icon } from "@/components/ds/icons";
import { Overline } from "@/components/ds/typography";

const AdminCalendarView = dynamic(() => import("@/components/admin/AdminCalendarView"), {
  ssr: false,
  loading: () => <div className="h-96 animate-pulse rounded-xl bg-rally-line/40" />,
});

function todayISO(): string {
  return new Date().toISOString().slice(0, 10);
}

function formatTimeRange(start: string, end: string): string {
  const fmt = (s: string) =>
    new Date(s).toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
  return `${fmt(start)} – ${fmt(end)}`;
}

function fillChip(enrolled: number, capacity: number): { variant: ChipVariant; label: string } {
  if (capacity <= 0) return { variant: "draft", label: "DRAFT" };
  const pct = enrolled / capacity;
  if (pct >= 1) return { variant: "full", label: "FULL" };
  if (pct >= 0.8) return { variant: "closing", label: "CLOSING" };
  return { variant: "open", label: "OPEN" };
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
    <section data-testid="admin-sessions" className="space-y-4">
      {/* Controls strip */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <ViewToggle view={view} onChange={setView} />
          {view === "table" && <DateInput value={date} onChange={setDate} />}
        </div>
        <Button
          variant="primary"
          size="sm"
          icon={Icon.plus(14, "currentColor")}
          onClick={() => setCreateOpen(true)}
          data-testid="admin-sessions-create"
        >
          Create session
        </Button>
      </div>

      {isError && (
        <Card p={16} style={{ borderColor: "#fecaca", background: "#fef2f2" }}>
          <div role="alert" className="flex items-center justify-between gap-3">
            <p className="text-sm text-red-800">Failed to load sessions.</p>
            <Button variant="secondary" size="sm" onClick={() => void refetch()}>
              Retry
            </Button>
          </div>
        </Card>
      )}

      {view === "calendar" ? (
        <Card p={16}>
          <AdminCalendarView sessions={sessions} />
        </Card>
      ) : isLoading ? (
        <TableSkeleton />
      ) : sessions.length === 0 ? (
        <Card p={32}>
          <p className="text-center text-sm text-rally-subtle" data-testid="sessions-empty">
            No sessions on {date}.
          </p>
        </Card>
      ) : (
        <SessionList
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

// ─────────────────────────────────────────────────────────────────────────────
// Controls
// ─────────────────────────────────────────────────────────────────────────────

function ViewToggle({
  view,
  onChange,
}: {
  view: "table" | "calendar";
  onChange: (v: "table" | "calendar") => void;
}) {
  return (
    <div className="inline-flex rounded-md border border-rally-line bg-white overflow-hidden">
      <PillButton active={view === "table"} onClick={() => onChange("table")}>
        Table
      </PillButton>
      <PillButton active={view === "calendar"} onClick={() => onChange("calendar")} divider>
        Calendar
      </PillButton>
    </div>
  );
}

function PillButton({
  active,
  divider,
  onClick,
  children,
}: {
  active: boolean;
  divider?: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      className="min-h-touch px-3.5 text-sm font-semibold transition-colors"
      style={{
        background: active ? "var(--rally-cobalt)" : "transparent",
        color: active ? "#fff" : "var(--rally-ink)",
        borderLeft: divider ? "1px solid var(--rally-line)" : "none",
      }}
    >
      {children}
    </button>
  );
}

function DateInput({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  return (
    <label className="inline-flex items-center gap-2">
      <span className="font-mono text-[10px] font-bold tracking-overline uppercase text-rally-muted">
        Date
      </span>
      <input
        type="date"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="rounded-md border border-rally-line bg-white px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-rally-cobalt-600/30"
      />
    </label>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Session list
// ─────────────────────────────────────────────────────────────────────────────

function SessionList({
  sessions,
  onDelete,
}: {
  sessions: AdminSessionView[];
  onDelete: (id: string) => void;
}) {
  return (
    <Card p={0}>
      <div className="overflow-x-auto">
        <table className="w-full text-sm" data-testid="admin-sessions-table">
          <thead>
            <tr className="border-b border-rally-line text-left">
              <Th>Session</Th>
              <Th>Location</Th>
              <Th>Time</Th>
              <Th>Coach</Th>
              <Th align="right">Fill</Th>
              <Th align="right">Waitlist</Th>
              <Th><span className="sr-only">Actions</span></Th>
            </tr>
          </thead>
          <tbody>
            {sessions.map((s) => {
              const fill = fillChip(s.enrolled_count, s.capacity);
              return (
                <tr
                  key={s.session_id}
                  data-testid={`session-row-${s.session_id}`}
                  className="border-b border-rally-line/60 last:border-0 hover:bg-rally-paper"
                >
                  <td className="px-4 py-3">
                    <a
                      href={`/admin/sessions/${s.session_id}`}
                      className="font-display font-semibold text-rally-ink hover:underline"
                    >
                      {s.title}
                    </a>
                  </td>
                  <td className="px-4 py-3 text-rally-muted">{s.location}</td>
                  <td className="px-4 py-3 font-mono tabular-nums text-rally-muted">
                    {formatTimeRange(s.start_at, s.end_at)}
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-2">
                      <Avatar name={s.coach_name || "Coach"} size={28} />
                      <span className="font-medium text-rally-ink">
                        {s.coach_name || "Coach assigned"}
                      </span>
                    </div>
                  </td>
                  <td className="px-4 py-3 text-right">
                    <div className="inline-flex items-center gap-2 justify-end">
                      <span className="font-mono font-semibold tabular-nums text-rally-ink">
                        {s.enrolled_count}/{s.capacity}
                      </span>
                      <Chip variant={fill.variant} label={fill.label} />
                    </div>
                  </td>
                  <td className="px-4 py-3 text-right font-mono tabular-nums text-rally-muted">
                    {s.waitlist_count}
                  </td>
                  <td className="px-4 py-3 text-right">
                    <Button
                      variant="danger"
                      size="sm"
                      onClick={() => onDelete(s.session_id)}
                      aria-label={`Cancel session ${s.title}`}
                    >
                      Cancel
                    </Button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

function Th({
  children,
  align = "left",
}: {
  children: React.ReactNode;
  align?: "left" | "right";
}) {
  return (
    <th
      className={`px-4 py-3 font-mono text-[10px] font-bold uppercase tracking-overline text-rally-muted ${
        align === "right" ? "text-right" : "text-left"
      }`}
    >
      {children}
    </th>
  );
}

function TableSkeleton() {
  return (
    <div className="space-y-2">
      {[0, 1, 2].map((i) => (
        <div key={i} className="h-14 animate-pulse rounded-xl bg-rally-line/40" />
      ))}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Create session dialog (Rally-styled)
// ─────────────────────────────────────────────────────────────────────────────

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
  const coachesQuery = useQuery({
    queryKey: queryKeys.admin.users("coach"),
    queryFn: () => listAdminUsers("coach"),
    enabled: open,
  });
  const coaches = coachesQuery.data?.users ?? [];

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
        <Dialog.Overlay className="fixed inset-0 z-50 bg-rally-ink/40" />
        <Dialog.Content
          className="fixed left-1/2 top-1/2 z-50 w-full max-w-md -translate-x-1/2 -translate-y-1/2 rounded-xl bg-white p-6 shadow-xl focus:outline-none"
          aria-describedby="create-session-desc"
        >
          <Overline>New session</Overline>
          <Dialog.Title className="font-display text-xl font-semibold tracking-[-0.01em] mt-1">
            Create session
          </Dialog.Title>
          <Dialog.Description id="create-session-desc" className="text-sm text-rally-muted mb-4 mt-1">
            Fill in the details below to schedule a new session.
          </Dialog.Description>

          {error && (
            <p
              role="alert"
              className="mb-3 rounded-md bg-red-50 px-3 py-2 text-sm text-red-700"
            >
              {error}
            </p>
          )}

          <form onSubmit={handleSubmit} className="space-y-3">
            <Field label="Coach" required>
              {coaches.length > 0 ? (
                <CoachSelect
                  coaches={coaches}
                  value={form.coach_id}
                  onChange={(coachId) => setForm((f) => ({ ...f, coach_id: coachId }))}
                />
              ) : (
                <input
                  type="text"
                  required
                  value={form.coach_id}
                  onChange={(e) => setForm((f) => ({ ...f, coach_id: e.target.value }))}
                  className={inputClass}
                  placeholder={coachesQuery.isLoading ? "Loading coaches…" : "Coach reference"}
                />
              )}
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
                <Button variant="secondary" size="sm" type="button">
                  Cancel
                </Button>
              </Dialog.Close>
              <Button
                variant="primary"
                size="sm"
                type="submit"
                disabled={mutation.isPending}
              >
                {mutation.isPending ? "Creating…" : "Create"}
              </Button>
            </div>
          </form>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

function CoachSelect({
  coaches,
  value,
  onChange,
}: {
  coaches: AdminUserView[];
  value: string;
  onChange: (coachId: string) => void;
}) {
  return (
    <select
      required
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className={inputClass}
    >
      <option value="">Select coach</option>
      {coaches.map((coach) => (
        <option key={coach.user_id} value={coach.user_id}>
          {coach.display_name} ({coach.email})
        </option>
      ))}
    </select>
  );
}

const inputClass =
  "w-full rounded-md border border-rally-line bg-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-rally-cobalt-600/30";

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
      <span className="mb-1 block font-mono text-[10px] font-bold uppercase tracking-overline text-rally-muted">
        {label}
        {required && <span aria-hidden="true" className="ml-1 text-red-500">*</span>}
      </span>
      {children}
    </label>
  );
}
