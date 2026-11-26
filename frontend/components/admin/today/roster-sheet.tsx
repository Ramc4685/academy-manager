"use client";

/**
 * S64: a class date's roster over the dashboard: who is in, attendance so far,
 * the parent's number to call, and (D-14) the health flag with the note on
 * tap. Health notes are read fresh on open, dropped on close, and never
 * printed: the print table carries the flag only.
 */

import { useState } from "react";
import Link from "next/link";
import type { Route } from "next";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import type {
  AdminChildHealth,
  AdminRosterHealth,
  AdminTodayClass,
  AdminTodayRosterRow,
} from "@/lib/api/admin";
import { telHref } from "@/lib/contact-links";
import { Button } from "@/components/ds/button";
import { Chip, type ChipVariant } from "@/components/ds/chip";
import { Modal } from "@/components/ds/modal";
import { PhoneList, PhoneListRow } from "@/components/ds/phone-row";
import { Overline } from "@/components/ds/typography";

import { rosterHealthQuery } from "./health-query";
import { classTimeRange, healthNotesLabel, todayDateLabel } from "./format";

export type RosterHealthState =
  | { kind: "off" }
  | { kind: "loading" }
  | { kind: "error"; onRetry: () => void; retrying: boolean }
  | { kind: "ready"; data: AdminRosterHealth };

export const PRINT_FOOTER =
  "⚑ Health note on file. Notes are not printed; open the roster on a phone to read them.";
const PRINT_UNCHECKED =
  "Health notes could not be checked when this was printed; open the roster on a phone.";

const PRINT_CSS = `
@media print {
  html, body { background: #fff !important; }
  body * { visibility: hidden !important; }
  .roster-print, .roster-print * { visibility: visible !important; }
  .roster-print { display: block !important; position: absolute !important; left: 0; top: 0; width: 100%; }
}
`;

function attendanceChip(row: AdminTodayRosterRow): { variant: ChipVariant; label: string } {
  if (row.attendance === "present") return { variant: "present", label: "PRESENT" };
  if (row.attendance === "late") return { variant: "late", label: "LATE" };
  if (row.attendance === "absent") return { variant: "absent", label: "ABSENT" };
  if (row.expected_absent) return { variant: "excused", label: "EXPECTED ABSENT" };
  return { variant: "draft", label: "NOT MARKED" };
}

function healthById(health: RosterHealthState): Map<string, AdminChildHealth> {
  if (health.kind !== "ready") return new Map();
  return new Map(health.data.children.map((child) => [child.student_id, child]));
}

function CallLink({ phone, name }: { phone: string | null | undefined; name: string }) {
  const href = telHref(phone);
  if (!href) return <span>no phone on file</span>;
  return (
    <a
      href={href}
      aria-label={`Call ${name}`}
      className="inline-flex min-h-touch items-center font-semibold text-rally-cobalt hover:underline"
    >
      {phone}
    </a>
  );
}

export function RosterSheetContent({
  cls,
  date,
  timezone,
  health,
  initialExpanded = [],
}: {
  cls: AdminTodayClass;
  date: string;
  timezone: string | null;
  health: RosterHealthState;
  initialExpanded?: string[];
}) {
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set(initialExpanded));
  const children = healthById(health);
  const time = classTimeRange(cls, timezone);
  const dayLine = [todayDateLabel(date), time, cls.location || null].filter(Boolean).join(" · ");
  const coach = cls.cover_coach_name ?? cls.coach_name;
  const declared = (studentId: string) => children.get(studentId)?.status === "declared";

  function toggle(studentId: string) {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(studentId)) next.delete(studentId);
      else next.add(studentId);
      return next;
    });
  }

  return (
    <div className="max-h-[75vh] space-y-3 overflow-y-auto" data-testid="admin-today-roster">
      <div>
        <Overline>Class date</Overline>
        <p className="mt-1 text-sm text-rally-ink">{dayLine}</p>
        {coach ? <p className="text-sm text-rally-muted">Coach {coach}</p> : null}
      </div>
      <div className="flex flex-wrap gap-2">
        <Button variant="secondary" size="sm" onClick={() => window.print()} data-testid="admin-today-print">
          Print roster
        </Button>
        <Link
          href={`/admin/sessions/${encodeURIComponent(cls.session_id)}` as Route}
          className="inline-flex h-[30px] items-center rounded-lg border border-rally-line bg-white px-3 text-xs font-semibold text-rally-ink hover:bg-rally-paper"
        >
          Open class
        </Link>
      </div>

      {health.kind === "ready" && health.data.declared_count > 0 ? (
        <p
          className="border-y border-rally-line py-2 text-sm font-semibold text-status-red-800"
          data-testid="admin-today-health-strip"
        >
          <span aria-hidden="true">⚑ </span>
          {healthNotesLabel(health.data.declared_count)} in this class
        </p>
      ) : null}
      {health.kind === "error" ? (
        <div
          role="status"
          className="flex flex-wrap items-center justify-between gap-2 border-y border-rally-line py-2 text-sm text-rally-muted"
          data-testid="admin-today-health-offline"
        >
          <span>Health notes need a connection.</span>
          <Button variant="secondary" size="sm" onClick={health.onRetry} disabled={health.retrying}>
            Retry
          </Button>
        </div>
      ) : null}

      {cls.roster.length === 0 ? (
        <p className="text-sm text-rally-subtle">No children in this class yet.</p>
      ) : (
        <PhoneList aria-label={`Roster for ${cls.title}`} className="-mx-4">
          {cls.roster.map((row) => {
            const chip = attendanceChip(row);
            const child = children.get(row.student_id);
            const open = expanded.has(row.student_id);
            const parent = row.parent_name ?? "Parent not on file";
            return (
              <PhoneListRow
                key={row.student_id}
                data-testid={`admin-today-roster-row-${row.student_id}`}
                title={
                  <span className="flex flex-wrap items-center gap-2">
                    <span>{row.full_name}</span>
                    {child?.status === "declared" ? (
                      <button
                        type="button"
                        aria-expanded={open}
                        aria-label={`Health note for ${row.full_name}`}
                        onClick={() => toggle(row.student_id)}
                        className="inline-flex min-h-touch min-w-touch items-center justify-center rounded-md text-status-red-800 hover:bg-status-red-50"
                      >
                        <span aria-hidden="true">⚑</span>
                      </button>
                    ) : null}
                    {row.kind === "trial" ? <Chip variant="trial" label="TRIAL" /> : null}
                    {row.kind === "makeup" ? <Chip variant="makeup" label="MAKE-UP" /> : null}
                  </span>
                }
                primary={<Chip variant={chip.variant} label={chip.label} />}
                secondary={
                  <>
                    <p className="flex flex-wrap items-center gap-x-1">
                      <span>{parent} ·</span>
                      <CallLink phone={row.parent_phone} name={parent} />
                    </p>
                    {child?.status === "none_declared" ? <p>Health: none declared</p> : null}
                    {child?.status === "not_answered" ? <p>Health: not answered</p> : null}
                    {child?.status === "declared" && open ? (
                      <div
                        className="rounded-lg border border-status-red-200 bg-status-red-50 p-3 text-rally-ink"
                        data-testid={`admin-today-health-note-${row.student_id}`}
                      >
                        <Overline>Health note</Overline>
                        <p className="mt-1 whitespace-pre-line text-sm">{child.note}</p>
                        <p className="mt-2 text-xs font-semibold text-rally-muted">Emergency contact</p>
                        {child.emergency_contact_name || child.emergency_contact_phone ? (
                          <p className="flex flex-wrap items-center gap-x-1 text-sm">
                            {child.emergency_contact_name ? <span>{child.emergency_contact_name} ·</span> : null}
                            <CallLink
                              phone={child.emergency_contact_phone}
                              name={child.emergency_contact_name ?? "emergency contact"}
                            />
                          </p>
                        ) : (
                          <p className="text-sm">Not on file</p>
                        )}
                      </div>
                    ) : null}
                  </>
                }
              />
            );
          })}
        </PhoneList>
      )}

      <RosterPrintTable cls={cls} date={date} timezone={timezone} health={health} declared={declared} />
      <style>{PRINT_CSS}</style>
    </div>
  );
}

/** D-14: names, parents and phones only. A declared note prints as ⚑, never its text. */
export function RosterPrintTable({
  cls,
  date,
  timezone,
  health,
  declared,
}: {
  cls: AdminTodayClass;
  date: string;
  timezone: string | null;
  health: RosterHealthState;
  declared: (studentId: string) => boolean;
}) {
  const coach = cls.cover_coach_name ?? cls.coach_name;
  const caption = [cls.title, todayDateLabel(date), classTimeRange(cls, timezone), coach ? `Coach ${coach}` : null]
    .filter(Boolean)
    .join(" · ");
  const anyDeclared = cls.roster.some((row) => declared(row.student_id));
  return (
    <div className="roster-print hidden" aria-hidden="true" data-testid="admin-today-print-table">
      <table className="w-full border-collapse text-sm">
        <caption className="pb-2 text-left font-semibold">{caption}</caption>
        <thead>
          <tr>
            <th scope="col" className="border-b p-1 text-left">#</th>
            <th scope="col" className="border-b p-1 text-left">Name</th>
            <th scope="col" className="border-b p-1 text-left">Parent</th>
            <th scope="col" className="border-b p-1 text-left">Phone</th>
            <th scope="col" className="border-b p-1 text-left">Here</th>
          </tr>
        </thead>
        <tbody>
          {cls.roster.map((row, i) => (
            <tr key={row.student_id}>
              <td className="border-b p-1">{i + 1}</td>
              <td className="border-b p-1">
                {row.full_name}
                {declared(row.student_id) ? " ⚑" : ""}
              </td>
              <td className="border-b p-1">{row.parent_name ?? ""}</td>
              <td className="border-b p-1">{row.parent_phone ?? ""}</td>
              <td className="border-b p-1">☐</td>
            </tr>
          ))}
        </tbody>
      </table>
      {anyDeclared ? <p className="mt-2 text-xs">{PRINT_FOOTER}</p> : null}
      {health.kind === "error" || health.kind === "loading" ? (
        <p className="mt-2 text-xs">{PRINT_UNCHECKED}</p>
      ) : null}
    </div>
  );
}

export function RosterSheet({
  cls,
  date,
  timezone,
  healthEnabled,
  onClose,
}: {
  cls: AdminTodayClass;
  date: string;
  timezone: string | null;
  healthEnabled: boolean;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const healthOn = healthEnabled && cls.phase !== "cancelled";
  const healthQuery = useQuery({ ...rosterHealthQuery(cls.occurrence_id), enabled: healthOn });
  const health: RosterHealthState = !healthOn
    ? { kind: "off" }
    : healthQuery.isSuccess
      ? { kind: "ready", data: healthQuery.data }
      : healthQuery.isError
        ? { kind: "error", onRetry: () => void healthQuery.refetch(), retrying: healthQuery.isFetching }
        : { kind: "loading" };

  function close() {
    queryClient.removeQueries({ queryKey: rosterHealthQuery(cls.occurrence_id).queryKey });
    onClose();
  }

  return (
    <Modal open onClose={close} title={cls.title} size="lg">
      <RosterSheetContent cls={cls} date={date} timezone={timezone} health={health} />
    </Modal>
  );
}
