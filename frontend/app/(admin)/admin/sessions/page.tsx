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
import type { Route } from "next";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import * as Dialog from "@radix-ui/react-dialog";

import {
  listAdminSessions,
  listAdminUsers,
  createAdminSession,
  updateAdminSession,
  deleteAdminSession,
  getAdminAcademy,
  type AdminSessionList,
  type AdminUserView,
  type AdminSessionView,
  type CreateSessionRequest,
  type EditSessionRequest,
} from "@/lib/api/admin";
// #503-class hardening: `hasRecurringSchedule` (and the `buildEditSessionForm`
// that depends on it) used to be copy-pasted here verbatim. The copy lacked the
// optional-chaining guard, so a payload without `days_of_week` crashed this page
// to the error boundary. One implementation now, so the two cannot drift again.
import { buildEditSessionForm, hasRecurringSchedule } from "./[id]/format";
import { ConfirmActionDialog } from "@/components/admin/confirm-action-dialog";
import { queryKeys } from "@/lib/query/keys";
import {
  formatAcademyTimeRange,
  parseAcademyInstant,
  resolveAcademyTimeZone,
} from "@/lib/format/academy-time";
import { actionCellClass, actionHeaderClass } from "@/lib/sticky-action-column";
import { useIsPhone } from "@/lib/use-is-phone";

import { Avatar } from "@/components/ds/avatar";
import { Button } from "@/components/ds/button";
import { Card } from "@/components/ds/card";
import { Chip, type ChipVariant } from "@/components/ds/chip";
import { PhoneList, PhoneListRow } from "@/components/ds/phone-row";
import { Icon } from "@/components/ds/icons";
import { Overline } from "@/components/ds/typography";

const AdminCalendarView = dynamic(() => import("@/components/admin/AdminCalendarView"), {
  ssr: false,
  loading: () => <div className="h-96 animate-pulse rounded-xl bg-rally-line/40" />,
});

function formatTimeRange(start: string, end: string, timezone: string | null): string {
  return formatAcademyTimeRange(start, end, timezone);
}

/**
 * Seed for the create-session form's timezone.
 *
 * This used to be the literal "UTC". A 6:00 PM Chicago class saved with
 * timezone "UTC" is stored as 18:00Z and then read back — by the parent
 * catalog, by monthly billing, and by payroll — as 1:00 PM Chicago: the class
 * silently moves five hours. Never guess UTC; prefer the academy's own zone,
 * and fall back to the admin's browser zone (they are almost always sitting in
 * the academy's city) rather than to a zone nobody chose. The value is shown
 * in a labelled, editable field so whatever we resolved is visible and
 * correctable before it is written.
 */
function seedTimezone(academyTimezone: string | null | undefined): string {
  return resolveAcademyTimeZone(academyTimezone).timeZone;
}
const DAYS_OF_WEEK = [
  { value: "Mon", label: "Monday" },
  { value: "Tue", label: "Tuesday" },
  { value: "Wed", label: "Wednesday" },
  { value: "Thu", label: "Thursday" },
  { value: "Fri", label: "Friday" },
  { value: "Sat", label: "Saturday" },
  { value: "Sun", label: "Sunday" },
] as const;

function formatClock(time: string | null | undefined): string {
  if (!time) return "";
  const [hourText = "0", minuteText = "00"] = time.split(":");
  const hour = Number(hourText);
  if (!Number.isFinite(hour)) return time;
  const period = hour >= 12 ? "PM" : "AM";
  const hour12 = hour % 12 || 12;
  return `${hour12}:${minuteText.padStart(2, "0")} ${period}`;
}

function formatSessionTimeRange(session: AdminSessionView): string {
  if (session.start_time && session.end_time) {
    return `${formatClock(session.start_time)} – ${formatClock(session.end_time)}`;
  }
  return formatTimeRange(session.start_at, session.end_at, session.timezone);
}

function formatCurrencyCents(cents: number | null | undefined): string {
  if (cents == null) return "—";
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: cents % 100 === 0 ? 0 : 2,
  }).format(cents / 100);
}

function centsToDollarsInput(cents: number | null | undefined): string {
  if (cents == null) return "";
  return cents % 100 === 0 ? String(cents / 100) : (cents / 100).toFixed(2);
}

function dollarsInputToCents(value: string): number | null {
  if (value.trim() === "") return null;
  const parsed = Number(value);
  if (!Number.isFinite(parsed) || parsed < 0) return null;
  return Math.round(parsed * 100);
}

function sessionDateLabel(session: AdminSessionView): string {
  return new Date(session.start_at).toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

/**
 * #847: the list showed a time range and no day, at any width — so "6:00 PM"
 * did not say whether it was the Tuesday class or the Saturday one. A
 * recurring session says which days it repeats on; a one-off says the weekday
 * of its own date, read in the session's timezone so it cannot drift by one
 * day for an admin in another zone.
 */
function sessionDayLabel(session: AdminSessionView): string {
  const days = session.days_of_week ?? [];
  if (days.length > 0) return days.join(", ");
  const { timeZone } = resolveAcademyTimeZone(session.timezone);
  return parseAcademyInstant(session.start_at).toLocaleDateString(undefined, {
    weekday: "short",
    timeZone,
  });
}

function fillChip(enrolled: number, capacity: number): { variant: ChipVariant; label: string } {
  if (capacity <= 0) return { variant: "draft", label: "DRAFT" };
  const pct = enrolled / capacity;
  if (pct >= 1) return { variant: "full", label: "FULL" };
  if (pct >= 0.8) return { variant: "closing", label: "CLOSING" };
  return { variant: "open", label: "OPEN" };
}

const CANCEL_FAILED_FALLBACK = "Could not cancel session.";

function cancelErrorMessage(err: unknown): string {
  const reason = err instanceof Error ? err.message.trim() : "";
  return reason ? `Could not cancel session: ${reason}` : CANCEL_FAILED_FALLBACK;
}

export default function AdminSessionsPage() {
  const [view, setView] = useState<"table" | "calendar">("table");
  const [createOpen, setCreateOpen] = useState(false);
  const [editSession, setEditSession] = useState<AdminSessionView | null>(null);
  const [cancelError, setCancelError] = useState<string | null>(null);
  // #838: cancelling a session is irreversible and mails every family, so the
  // row button now opens a dialog that names it and counts who is affected.
  const [cancelTarget, setCancelTarget] = useState<AdminSessionView | null>(null);
  const queryClient = useQueryClient();

  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: queryKeys.admin.sessions("upcoming"),
    queryFn: () => listAdminSessions(undefined, { window: "upcoming" }),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => deleteAdminSession(id),
    onMutate: () => {
      setCancelError(null);
    },
    onSuccess: () => {
      setCancelError(null);
      void queryClient.invalidateQueries({ queryKey: queryKeys.admin.sessions("upcoming") });
    },
    // #467: without this, a 403/404/500 was swallowed by `.mutate()` and the
    // cancel looked identical to a success.
    onError: (err: unknown) => {
      // The reason is folded into the message here, not at render time: an API
      // error can carry an EMPTY message (`makeError` builds `new Error("")`
      // for a non-JSON body), and rendering a fixed prefix beside the fallback
      // string produced "Could not cancel session: Could not cancel session."
      setCancelError(cancelErrorMessage(err));
    },
  });

  const sessions = data?.sessions ?? [];

  return (
    <section data-testid="admin-sessions" className="space-y-4">
      {/* Controls strip */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-3">
          <ViewToggle view={view} onChange={setView} />
          <span className="font-mono text-[10px] font-bold uppercase tracking-overline text-rally-muted">
            Upcoming academy sessions
          </span>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          {/* The waitlist is a queue on the Inbox, not its own page; the old
              sidebar entry pointed at /admin/waitlist, which does not exist. */}
          <Link
            href={"/admin/inbox?tab=waitlist" as Route}
            className="inline-flex min-h-touch items-center text-sm font-medium text-rally-cobalt-700 hover:underline"
            data-testid="admin-sessions-waitlist-link"
          >
            Waitlist
          </Link>
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

      {cancelError && (
        <Card p={16} style={{ borderColor: "#fecaca", background: "#fef2f2" }}>
          <div role="alert" data-testid="admin-sessions-cancel-error" className="flex items-center justify-between gap-3">
            <p className="text-sm text-red-800">{cancelError}</p>
            <Button variant="secondary" size="sm" onClick={() => setCancelError(null)}>
              Dismiss
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
            No upcoming sessions found.
          </p>
        </Card>
      ) : (
        <SessionList
          sessions={sessions}
          onEdit={setEditSession}
          onDelete={setCancelTarget}
          pendingDeleteId={deleteMutation.isPending ? (deleteMutation.variables ?? null) : null}
        />
      )}

      {cancelTarget && (
        <ConfirmActionDialog
          open
          onOpenChange={(open) => !open && setCancelTarget(null)}
          overline="Cancel session"
          title="Cancel this session for everyone?"
          subject={`${cancelTarget.title} · ${cancelTarget.location}`}
          consequence={
            <>
              <p>
                {cancelTarget.enrolled_count === 1 ? "1 family" : `${cancelTarget.enrolled_count} families`}{" "}
                {cancelTarget.enrolled_count === 1 ? "loses its" : "lose their"} seat, and{" "}
                {cancelTarget.waitlist_count === 1 ? "1 family" : `${cancelTarget.waitlist_count} families`} on
                the waitlist {cancelTarget.waitlist_count === 1 ? "is" : "are"} dropped. Billing for
                the session stops; invoices already raised stay and must be voided or credited by
                hand.
              </p>
              <p>Every enrolled family is emailed that the session was cancelled.</p>
              <p className="font-semibold text-rally-ink">This cannot be undone.</p>
            </>
          }
          confirmLabel="Cancel session"
          pending={deleteMutation.isPending}
          onConfirm={() => {
            deleteMutation.mutate(cancelTarget.session_id);
            setCancelTarget(null);
          }}
        />
      )}

      <CreateSessionDialog
        open={createOpen}
        onOpenChange={setCreateOpen}
        onCreated={() => {
          setCreateOpen(false);
          void queryClient.invalidateQueries({ queryKey: queryKeys.admin.sessions("upcoming") });
        }}
      />
      <EditSessionDialog
        session={editSession}
        onOpenChange={(open) => {
          if (!open) setEditSession(null);
        }}
        onSaved={(savedSession) => {
          setEditSession(null);
          queryClient.setQueryData<AdminSessionList | undefined>(
            queryKeys.admin.sessions("upcoming"),
            (current) =>
              current
                ? {
                    sessions: current.sessions.map((session) =>
                      session.session_id === savedSession.session_id ? savedSession : session,
                    ),
                  }
                : current,
          );
          queryClient.setQueryData(queryKeys.admin.sessionDetail(savedSession.session_id), savedSession);
          void queryClient.invalidateQueries({ queryKey: queryKeys.admin.sessions("upcoming") });
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

// ─────────────────────────────────────────────────────────────────────────────
// Session list
// ─────────────────────────────────────────────────────────────────────────────

function SessionList({
  sessions,
  onEdit,
  onDelete,
  pendingDeleteId,
}: {
  sessions: AdminSessionView[];
  onEdit: (session: AdminSessionView) => void;
  onDelete: (session: AdminSessionView) => void;
  pendingDeleteId: string | null;
}) {
  const isPhone = useIsPhone();

  if (isPhone) {
    return (
      <Card p={0}>
        {/* #847: the `admin-sessions-table` hook moves to the wrapper that
            holds WHICHEVER layout is mounted, so specs that scope row lookups
            to "the sessions list" keep working at phone width. */}
        <div data-testid="admin-sessions-table">
          <SessionPhoneList
            sessions={sessions}
            onEdit={onEdit}
            onDelete={onDelete}
            pendingDeleteId={pendingDeleteId}
          />
        </div>
      </Card>
    );
  }

  return (
    <Card p={0}>
      <div className="overflow-x-auto" data-testid="admin-sessions-table">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-rally-line text-left">
              <Th>Session</Th>
              <Th>Location</Th>
              <Th>Day</Th>
              <Th>Time</Th>
              <Th>Coach</Th>
              <Th align="right">Fee</Th>
              <Th align="right">Fill</Th>
              <Th align="right">Waitlist</Th>
              {/* #847: a ninth column pushed Edit/Cancel past the fold at
                  1280. Sticky keeps them on screen at every width. */}
              <Th className={actionHeaderClass}><span className="sr-only">Actions</span></Th>
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
                  <td className="px-4 py-3 whitespace-nowrap text-rally-muted">
                    {sessionDayLabel(s)}
                  </td>
                  <td className="px-4 py-3 font-mono tabular-nums text-rally-muted">
                    {formatSessionTimeRange(s)}
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-2">
                      <Avatar name={s.coach_name || "Coach"} size={28} />
                      <span className="font-medium text-rally-ink">
                        {s.coach_name || "Coach assigned"}
                      </span>
                    </div>
                  </td>
                  <td className="px-4 py-3 text-right font-mono font-semibold tabular-nums text-rally-ink">
                    {formatCurrencyCents(s.amount_cents)}
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
                  <td className={`${actionCellClass} bg-white text-right`}>
                    <div className="flex justify-end gap-2">
                      <Button
                        variant="secondary"
                        size="sm"
                        onClick={() => onEdit(s)}
                        aria-label={`Edit session ${s.title}`}
                      >
                        Edit
                      </Button>
                      <Button
                        variant="danger"
                        size="sm"
                        onClick={() => onDelete(s)}
                        disabled={pendingDeleteId !== null}
                        aria-label={`Cancel session ${s.title}`}
                      >
                        {pendingDeleteId === s.session_id ? "Cancelling…" : "Cancel"}
                      </Button>
                    </div>
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

/**
 * #847: at 400px the table's Fill, Waitlist, Edit and Cancel all sat past the
 * right edge — which is why `local-auth-sessions.spec.ts` had to be pinned to
 * a desktop viewport. Every one of them is on screen here, and Edit/Cancel
 * live behind a 44px menu trigger.
 */
function SessionPhoneList({
  sessions,
  onEdit,
  onDelete,
  pendingDeleteId,
}: {
  sessions: AdminSessionView[];
  onEdit: (session: AdminSessionView) => void;
  onDelete: (session: AdminSessionView) => void;
  pendingDeleteId: string | null;
}) {
  return (
    <PhoneList aria-label="Sessions">
      {sessions.map((s) => {
        const fill = fillChip(s.enrolled_count, s.capacity);
        return (
          <PhoneListRow
            key={s.session_id}
            data-testid={`session-row-${s.session_id}`}
            title={s.title}
            href={`/admin/sessions/${s.session_id}` as Route}
            primary={
              <span className="inline-flex items-center gap-2">
                <span className="font-mono text-sm font-semibold tabular-nums text-rally-ink">
                  {s.enrolled_count}/{s.capacity}
                </span>
                <Chip variant={fill.variant} label={fill.label} />
              </span>
            }
            actionsLabel={`Actions for ${s.title}`}
            // Not `session-row-actions-*`: saas-tenant-isolation.spec.ts scopes
            // a leak check to `[data-testid^="session-row-"]`, and that prefix
            // would otherwise match this trigger too, double-counting every
            // row.
            actionsTestId={`session-actions-${s.session_id}`}
            actions={[
              {
                key: "open",
                label: "Open session",
                href: `/admin/sessions/${s.session_id}` as Route,
              },
              { key: "edit", label: "Edit", onSelect: () => onEdit(s) },
              {
                key: "cancel",
                label: pendingDeleteId === s.session_id ? "Cancelling…" : "Cancel session",
                danger: true,
                disabled: pendingDeleteId !== null,
                onSelect: () => onDelete(s),
              },
            ]}
            secondary={
              <>
                <div className="font-mono text-xs tabular-nums text-rally-base">
                  {sessionDayLabel(s)} · {formatSessionTimeRange(s)}
                </div>
                <div className="break-words">
                  {s.location} · {s.coach_name || "Coach assigned"}
                </div>
                <div className="font-mono text-xs tabular-nums">
                  {formatCurrencyCents(s.amount_cents)} · {s.waitlist_count} on waitlist
                </div>
              </>
            }
          />
        );
      })}
    </PhoneList>
  );
}

function EditSessionDialog({
  session,
  onOpenChange,
  onSaved,
}: {
  session: AdminSessionView | null;
  onOpenChange: (open: boolean) => void;
  onSaved: (session: AdminSessionView) => void;
}) {
  const [form, setForm] = useState<EditSessionRequest>({});
  const [error, setError] = useState<string | null>(null);
  const open = session !== null;
  const coachesQuery = useQuery({
    queryKey: queryKeys.admin.users("coach"),
    queryFn: () => listAdminUsers("coach"),
    enabled: open,
  });
  const coaches = coachesQuery.data?.users ?? [];

  const mutation = useMutation({
    mutationFn: (payload: EditSessionRequest) => updateAdminSession(session!.session_id, payload),
    onSuccess: (savedSession) => {
      setError(null);
      onSaved(savedSession);
    },
    onError: (err: Error) => setError(err.message ?? "Failed to update session."),
  });

  useEffect(() => {
    if (!session) return;
    setForm(buildEditSessionForm(session));
  }, [session]);

  const recurring = session ? hasRecurringSchedule(session) : false;
  const selectedDays = form.days_of_week ?? [];

  return (
    <Dialog.Root
      open={open}
      onOpenChange={(nextOpen) => {
        if (!nextOpen) {
          setForm({});
          setError(null);
        }
        onOpenChange(nextOpen);
      }}
    >
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 bg-rally-ink/40" />
        <Dialog.Content className="fixed left-1/2 top-1/2 z-50 w-full max-w-md -translate-x-1/2 -translate-y-1/2 rounded-xl bg-white p-6 shadow-xl focus:outline-none">
          <Overline>Session</Overline>
          <Dialog.Title className="mt-1 font-display text-xl font-semibold tracking-[-0.01em]">
            Edit session
          </Dialog.Title>
          <Dialog.Description className="mb-4 mt-1 text-sm text-rally-muted">
            Update recurring schedule, capacity, and coach assignment.
          </Dialog.Description>
          {error && (
            <p role="alert" className="mb-3 rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">
              {error}
            </p>
          )}
          <form
            className="space-y-3"
            onSubmit={(event) => {
              event.preventDefault();
              mutation.mutate(form);
            }}
          >
            <Field label="Coach">
              {coaches.length > 0 ? (
                <CoachSelect
                  coaches={coaches}
                  value={form.coach_id ?? ""}
                  onChange={(coachId) => setForm((f) => ({ ...f, coach_id: coachId }))}
                />
              ) : (
                <input
                  type="text"
                  value={form.coach_id ?? ""}
                  onChange={(event) => setForm((f) => ({ ...f, coach_id: event.target.value }))}
                  className={inputClass}
                  placeholder={coachesQuery.isLoading ? "Loading coaches…" : "Coach reference"}
                />
              )}
            </Field>
            <Field label="Name">
              <input
                type="text"
                value={form.title ?? ""}
                onChange={(event) => setForm((f) => ({ ...f, title: event.target.value }))}
                className={inputClass}
              />
            </Field>
            <Field label="Location">
              <input
                type="text"
                value={form.location ?? ""}
                onChange={(event) => setForm((f) => ({ ...f, location: event.target.value }))}
                className={inputClass}
              />
            </Field>
            <div className="grid grid-cols-2 gap-3">
              <Field label={recurring ? "Day of week" : "Date"}>
                {recurring ? (
                  selectedDays.length <= 1 ? (
                    <DaySelect
                      value={selectedDays[0] ?? "Wed"}
                      onChange={(day) => setForm((f) => ({ ...f, days_of_week: [day] }))}
                    />
                  ) : (
                    <input value={selectedDays.join(", ")} readOnly className={inputClass} />
                  )
                ) : (
                  <input value={session ? sessionDateLabel(session) : ""} readOnly className={inputClass} />
                )}
              </Field>
              <Field label="Start time">
                <input
                  type="time"
                  value={form.start_time ?? ""}
                  onChange={(event) => setForm((f) => ({ ...f, start_time: event.target.value }))}
                  className={inputClass}
                  disabled={!recurring}
                />
              </Field>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <Field label="End time">
                <input
                  type="time"
                  value={form.end_time ?? ""}
                  onChange={(event) => setForm((f) => ({ ...f, end_time: event.target.value }))}
                  className={inputClass}
                  disabled={!recurring}
                />
              </Field>
              <Field label="Capacity">
                <input
                  type="number"
                  min={1}
                  value={form.capacity ?? 1}
                  onChange={(event) =>
                    setForm((f) => ({ ...f, capacity: parseInt(event.target.value, 10) || 1 }))
                  }
                  className={inputClass}
                />
              </Field>
            </div>
            <Field label="Monthly fee">
              <input
                type="number"
                min={0}
                step="0.01"
                value={centsToDollarsInput(form.amount_cents)}
                onChange={(event) =>
                  setForm((f) => ({
                    ...f,
                    amount_cents: dollarsInputToCents(event.target.value),
                  }))
                }
                className={inputClass}
              />
            </Field>
            <Field label="Reason">
              <input
                value={form.reason ?? ""}
                onChange={(event) => setForm((f) => ({ ...f, reason: event.target.value }))}
                className={inputClass}
                placeholder="Optional"
              />
            </Field>
            <div className="flex justify-end gap-2 pt-2">
              <Dialog.Close asChild>
                <Button variant="secondary" size="sm" type="button">
                  Cancel
                </Button>
              </Dialog.Close>
              <Button variant="primary" size="sm" type="submit" disabled={mutation.isPending}>
                {mutation.isPending ? "Saving…" : "Save"}
              </Button>
            </div>
          </form>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

function Th({
  children,
  align = "left",
  className,
}: {
  children: React.ReactNode;
  align?: "left" | "right";
  className?: string;
}) {
  return (
    <th
      className={`px-4 py-3 font-mono text-[10px] font-bold uppercase tracking-overline text-rally-muted ${
        align === "right" ? "text-right" : "text-left"
      } ${className ?? ""}`}
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
  days_of_week: ["Wed"],
  start_time: "18:00",
  end_time: "18:45",
  timezone: null,
  capacity: 10,
  amount_cents: null,
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

  const academyQuery = useQuery({
    queryKey: queryKeys.admin.academy(),
    queryFn: getAdminAcademy,
    staleTime: 10 * 60 * 1000,
  });

  const academyTimezone = academyQuery.data?.timezone;
  const wasOpen = useRef(false);

  // Issue #148: this used to replace the whole form object whenever the academy
  // timezone resolved, so a slow query wiped whatever the admin had already
  // typed into an open dialog. Seed defaults on open; afterwards patch only the
  // timezone field, and only while the admin has not touched it.
  const [timezoneTouched, setTimezoneTouched] = useState(false);
  useEffect(() => {
    if (open && !wasOpen.current) {
      setForm({ ...EMPTY_FORM, timezone: seedTimezone(academyTimezone) });
      setTimezoneTouched(false);
      setError(null);
    } else if (open && academyTimezone && !timezoneTouched) {
      // The academy query resolved after the dialog opened, so the seed was the
      // browser-zone fallback. Adopt the academy's real zone.
      setForm((current) => ({ ...current, timezone: academyTimezone }));
    }
    wasOpen.current = open;
  }, [open, academyTimezone, timezoneTouched]);

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
            Create a weekly recurring session.
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
            <Field label="Name" required>
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
              <Field label="Day of week" required>
                <DaySelect
                  value={form.days_of_week?.[0] ?? "Wed"}
                  onChange={(day) => setForm((f) => ({ ...f, days_of_week: [day] }))}
                />
              </Field>
              <Field label="Start time" required>
                <input
                  type="time"
                  required
                  value={form.start_time ?? ""}
                  onChange={(e) => setForm((f) => ({ ...f, start_time: e.target.value }))}
                  className={inputClass}
                />
              </Field>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <Field label="End time" required>
                <input
                  type="time"
                  required
                  value={form.end_time ?? ""}
                  onChange={(e) => setForm((f) => ({ ...f, end_time: e.target.value }))}
                  className={inputClass}
                />
              </Field>
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
            </div>
            {/* Visible and editable: the start/end times above are wall-clock
                times in THIS zone, and the zone is what billing and payroll
                re-derive every occurrence from. A hidden default here moves a
                real class by hours. */}
            <Field label="Timezone" required>
              <input
                type="text"
                required
                value={form.timezone ?? ""}
                onChange={(e) => {
                  setTimezoneTouched(true);
                  setForm((f) => ({ ...f, timezone: e.target.value }));
                }}
                className={inputClass}
                aria-describedby="create-session-tz-hint"
                data-testid="create-session-timezone"
              />
              <p id="create-session-tz-hint" className="mt-1 text-xs text-rally-muted">
                {academyTimezone
                  ? "From your academy settings."
                  : "Your academy has no timezone set — this defaulted to your browser's zone. Confirm it before saving."}
              </p>
            </Field>
            <Field label="Monthly fee" required>
              <input
                type="number"
                required
                min={0}
                step="0.01"
                value={centsToDollarsInput(form.amount_cents)}
                onChange={(e) =>
                  setForm((f) => ({
                    ...f,
                    amount_cents: dollarsInputToCents(e.target.value),
                  }))
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

function DaySelect({
  value,
  onChange,
}: {
  value: string;
  onChange: (day: string) => void;
}) {
  return (
    <select required value={value} onChange={(e) => onChange(e.target.value)} className={inputClass}>
      {DAYS_OF_WEEK.map((day) => (
        <option key={day.value} value={day.value}>
          {day.label}
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
