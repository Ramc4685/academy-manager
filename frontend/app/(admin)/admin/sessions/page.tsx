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
import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";

import {
  listAdminSessions,
  deleteAdminSession,
  type AdminSessionList,
  type AdminSessionView,
} from "@/lib/api/admin";
import { ConfirmActionDialog } from "@/components/admin/confirm-action-dialog";
// One class form for Create, list Edit and class-page Edit (class-page PR A).
import { CreateClassDialog, EditClassDialog } from "@/components/admin/sessions/class-form";
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

const AdminCalendarView = dynamic(() => import("@/components/admin/AdminCalendarView"), {
  ssr: false,
  loading: () => <div className="h-96 animate-pulse rounded-xl bg-rally-line/40" />,
});

function formatTimeRange(start: string, end: string, timezone: string | null): string {
  return formatAcademyTimeRange(start, end, timezone);
}

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
  // Set when a class was created but its price plan link failed.
  const [createWarning, setCreateWarning] = useState<string | null>(null);
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

      {createWarning && (
        <Card p={16} style={{ borderColor: "#fde68a", background: "#fffbeb" }}>
          <div role="status" data-testid="admin-sessions-create-warning" className="flex items-center justify-between gap-3">
            <p className="text-sm text-amber-900">{createWarning}</p>
            <Button variant="secondary" size="sm" onClick={() => setCreateWarning(null)}>
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

      <CreateClassDialog
        open={createOpen}
        onOpenChange={setCreateOpen}
        onCreated={(_created, warning) => {
          setCreateOpen(false);
          setCreateWarning(warning ?? null);
          void queryClient.invalidateQueries({ queryKey: queryKeys.admin.sessions("upcoming") });
        }}
      />
      <EditClassDialog
        open={editSession !== null}
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
