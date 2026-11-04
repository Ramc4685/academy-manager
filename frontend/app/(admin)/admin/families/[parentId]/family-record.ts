/**
 * People CRM family record page (Lane A4): the pure parts of the tab shell,
 * the Details tab and the child drawer, kept here so they are tested without
 * rendering. Spec: docs/design/people-crm/engineering-spec.md §4.
 */
import type {
  CorrectableAttendanceStatus,
  FamilyIndexChild,
  FamilyIndexRow,
  FamilyParent,
  FamilyStudent,
} from "@/lib/api/admin-families";
import type { AdminStudentRecentAttendance } from "@/lib/api/v2/students";

import { shortDate } from "./family-view";

// ---------------------------------------------------------------------------
// Tabs: `?tab=` on the existing /admin/families/[parentId] route.
// ---------------------------------------------------------------------------

export type FamilyTab = "overview" | "notes" | "details" | "billing" | "messages" | "timeline";

export const FAMILY_TABS: ReadonlyArray<{ id: FamilyTab; label: string }> = [
  { id: "overview", label: "Overview" },
  { id: "notes", label: "Notes & follow-ups" },
  { id: "details", label: "Details" },
  { id: "billing", label: "Billing" },
  { id: "messages", label: "Messages" },
  { id: "timeline", label: "Timeline" },
];

/** The tab a `?tab=` value asks for; Overview for anything unrecognised. */
export function resolveFamilyTab(value: string | null | undefined): FamilyTab {
  return FAMILY_TABS.some((tab) => tab.id === value) ? (value as FamilyTab) : "overview";
}

/**
 * The query string for a tab, keeping every other param. Overview is the
 * default, so it drops `tab` rather than writing `?tab=overview`.
 */
export function familyTabQuery(current: string, next: FamilyTab): string {
  const params = new URLSearchParams(current);
  if (next === "overview") params.delete("tab");
  else params.set("tab", next);
  const query = params.toString();
  return query ? `?${query}` : "?";
}

/**
 * Where to send a record opened by a parent alias: the canonical family URL
 * with the same query (so `?tab=` survives), or null when the URL is already
 * canonical or the record has not loaded.
 */
export function canonicalFamilyHref(
  urlId: string,
  canonicalId: string | null | undefined,
  query: string,
): string | null {
  if (!canonicalId || canonicalId === urlId) return null;
  const path = `/admin/families/${encodeURIComponent(canonicalId)}`;
  return query ? `${path}?${query}` : path;
}

/** Arrow-key movement across the tablist (WAI-ARIA tabs pattern). */
export function adjacentFamilyTab(current: FamilyTab, key: string): FamilyTab | null {
  const index = FAMILY_TABS.findIndex((tab) => tab.id === current);
  if (key === "ArrowRight") return FAMILY_TABS[(index + 1) % FAMILY_TABS.length].id;
  if (key === "ArrowLeft")
    return FAMILY_TABS[(index - 1 + FAMILY_TABS.length) % FAMILY_TABS.length].id;
  if (key === "Home") return FAMILY_TABS[0].id;
  if (key === "End") return FAMILY_TABS[FAMILY_TABS.length - 1].id;
  return null;
}

// ---------------------------------------------------------------------------
// Details tab: read-only contact data that already exists.
// ---------------------------------------------------------------------------

export interface ContactRow {
  label: string;
  value: string;
  testId: string;
}

/**
 * The primary parent's contact fields. The family index row is the source
 * (it is what the Families view shows); the billing view's parent block fills
 * a gap when the index could not be read.
 */
export function primaryContactRows(
  family: FamilyIndexRow | null,
  parent: FamilyParent | null,
): ContactRow[] {
  const name = family?.parent_name ?? parent?.name ?? null;
  const email = family?.email ?? parent?.email ?? null;
  const phone = family?.phone ?? parent?.phone ?? null;
  return [
    { label: "Name", value: name ?? "Not on file", testId: "details-parent-name" },
    { label: "Email", value: email ?? "Not on file", testId: "details-parent-email" },
    { label: "Phone", value: phone ?? "Not on file", testId: "details-parent-phone" },
  ];
}

// ---------------------------------------------------------------------------
// Children: Overview list and the child drawer.
// ---------------------------------------------------------------------------

export interface OverviewChild {
  studentId: string;
  name: string;
  lifecycle: string | null;
  lifecycleAsOf: string | null;
  classes: string[];
}

/**
 * The children to list on Overview. The index row carries lifecycle and
 * classes; a child only the billing view knows (the index was unavailable)
 * is still listed, with its enrolment titles.
 */
export function overviewChildren(
  family: FamilyIndexRow | null,
  students: FamilyStudent[],
): OverviewChild[] {
  const out: OverviewChild[] = (family?.children ?? []).map((child: FamilyIndexChild) => ({
    studentId: child.student_id,
    name: child.name,
    lifecycle: child.lifecycle,
    lifecycleAsOf: child.lifecycle_as_of,
    classes: child.classes.map((c) => c.title),
  }));
  const seen = new Set(out.map((c) => c.studentId));
  for (const s of students) {
    if (seen.has(s.student_id)) continue;
    out.push({
      studentId: s.student_id,
      name: s.name,
      lifecycle: null,
      lifecycleAsOf: null,
      classes: s.enrollments
        .filter((e) => e.status === "active" || e.status === "paused")
        .map((e) => e.session_title ?? "Class"),
    });
  }
  return out;
}

/** DOM id of a child's drawer trigger: focus goes back there on close. */
export function childTriggerId(studentId: string): string {
  return `family-child-open-${studentId}`;
}

export const CORRECTABLE_STATUSES: readonly CorrectableAttendanceStatus[] = [
  "present",
  "late",
  "absent",
];

const STATUS_LABELS: Record<string, string> = {
  present: "Present",
  late: "Late",
  absent: "Absent",
  excused: "Excused",
  voided: "Voided",
};

export function attendanceStatusLabel(status: string | null | undefined): string {
  if (!status) return "Unknown";
  return STATUS_LABELS[status] ?? status.charAt(0).toUpperCase() + status.slice(1);
}

export interface DrawerAttendanceRow {
  key: string;
  occurrenceId: string | null;
  dateLabel: string;
  status: string;
  statusLabel: string;
  /** "Was Present" once corrected; null for an untouched mark. */
  correctedNote: string | null;
  /** Only a mark with an occurrence and a real status can be corrected. */
  correctable: boolean;
}

function isCorrectable(status: string): status is CorrectableAttendanceStatus {
  return (CORRECTABLE_STATUSES as readonly string[]).includes(status);
}

/** The drawer's recent marks, newest first as the API returns them. */
export function drawerAttendanceRows(
  recent: AdminStudentRecentAttendance[],
): DrawerAttendanceRow[] {
  return recent.map((row, index) => {
    const occurrenceId = row.occurrence_id ?? null;
    const dateLabel = shortDate(row.date) ?? shortDate(row.marked_at ?? null) ?? "Undated";
    return {
      key: occurrenceId ?? `${row.session_id}-${row.date}-${index}`,
      occurrenceId,
      dateLabel,
      status: row.status,
      statusLabel: attendanceStatusLabel(row.status),
      correctedNote: row.previous_status
        ? `Was ${attendanceStatusLabel(row.previous_status)}`
        : null,
      correctable: occurrenceId !== null && isCorrectable(row.status),
    };
  });
}

/** The statuses a mark can be corrected to: every real status but its own. */
export function correctionTargets(current: string): CorrectableAttendanceStatus[] {
  return CORRECTABLE_STATUSES.filter((s) => s !== current);
}

/** DOM id of a mark's Correct button: focus returns there after a save. */
export function correctTriggerId(occurrenceId: string): string {
  return `drawer-correct-${occurrenceId}`;
}

/**
 * The confirm step's copy: says exactly which mark changes, from what to
 * what, and that the old status is kept.
 */
export function correctionConfirmCopy(args: {
  childName: string;
  dateLabel: string;
  from: string;
  to: CorrectableAttendanceStatus;
}): string {
  return `Change ${args.childName}'s ${args.dateLabel} mark from ${attendanceStatusLabel(
    args.from,
  )} to ${attendanceStatusLabel(args.to)}? The old mark, your name and the reason are kept in the attendance history.`;
}
