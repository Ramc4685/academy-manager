"use client";

/**
 * Admin student detail page.
 *
 * Pulls a single student from the v2 BFF and exposes safe admin-editable
 * fields. No raw internal ids are rendered in normal UI.
 */

import { type ReactNode, useEffect, useState } from "react";
import Link from "next/link";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Activity,
  ArrowLeft,
  CalendarCheck,
  FileCheck,
  MoreVertical,
  ShieldCheck,
  UserRound,
  Wallet,
} from "lucide-react";

import { listAdminUsers } from "@/lib/api/admin";
import { getAdminStudent, type AdminStudentDetail } from "@/lib/api/v2/students";
import { getActiveAcademyId } from "@/lib/api/client";
import { getStudentProgress, listPrograms } from "@/lib/api/curriculum";
import { getDeparturePolicy } from "@/lib/api/v2/departure-policy";
import { buildStudentProgressHref } from "@/lib/navigation/admin-student-progress-return";
import { queryKeys } from "@/lib/query/keys";
import { Avatar } from "@/components/ds/avatar";
import { Button } from "@/components/ds/button";
import { Card } from "@/components/ds/card";
import { Overline } from "@/components/ds/typography";
import { StopAllClassesDialog } from "@/components/admin/enrollment/stop-all-classes-dialog";
import { useUnsavedChanges } from "@/components/admin/unsaved-changes-guard";
import { Chip } from "@/components/ds/chip";
import { ContactLinks } from "@/components/ds/contact-links";
import { OverflowMenu } from "@/components/ds/menu";
import { lifecycleLabel, lifecycleVariant } from "@/lib/format/lifecycle-copy";
import {
  STUDENT_TABS,
  resolveStudentTab,
  studentDocumentTitle,
  type StudentTab,
} from "@/lib/admin/student-tabs";

import { BillingEnrollmentsPanel } from "./BillingEnrollmentsPanel";
import { DetailList } from "./DetailList";
import { FamilyBillingLink } from "./FamilyBillingLink";
import { formatCurrencyCents, formatDate, formatDateTime, formatDateUtc } from "./format";
import { SessionsPanel } from "./SessionsPanel";
import { OPEN_BILLING_STATUSES, StatusChip } from "./StatusChip";
import { ChangeParentPanel, StudentEditForm } from "./StudentEditForm";

export default function AdminStudentDetailPage() {
  const params = useParams<{ studentId: string }>();
  const studentId = params?.studentId ?? "";
  const queryClient = useQueryClient();
  const router = useRouter();
  const searchParams = useSearchParams();
  // #839: the tab is in the URL, so a link to a student's Billing is a link
  // to their Billing and a reload does not drop back to Overview.
  const activeTab = resolveStudentTab(searchParams.get("tab"));
  const [stopAllClassesOpen, setStopAllClassesOpen] = useState(false);
  const { requestLeave } = useUnsavedChanges();

  // UI-2: only the active tab's panel is mounted, so switching tabs unmounts
  // the form holding a draft. The tabs are buttons, not links, so the shell
  // guard's link listener never sees them; ask it explicitly instead.
  function selectTab(next: StudentTab) {
    if (next === activeTab) return;
    requestLeave(() => setActiveTab(next));
  }

  function setActiveTab(next: StudentTab) {
    const nextParams = new URLSearchParams(searchParams.toString());
    if (next === "overview") nextParams.delete("tab");
    else nextParams.set("tab", next);
    const query = nextParams.toString();
    router.replace(query ? `?${query}` : "?", { scroll: false });
  }

  const departurePolicyQuery = useQuery({
    queryKey: queryKeys.admin.departurePolicy(),
    queryFn: getDeparturePolicy,
  });

  const studentQuery = useQuery({
    queryKey: queryKeys.admin.studentDetail(studentId),
    queryFn: () => getAdminStudent(studentId),
    enabled: Boolean(studentId),
    retry: false,
  });
  const parentsQuery = useQuery({
    queryKey: queryKeys.admin.users("parent"),
    queryFn: () => listAdminUsers("parent"),
    enabled: Boolean(studentId),
  });

  // #839: every open student tab said "Students", so a row of them was
  // unreadable. The shell title is static, so the page names itself.
  const studentName = studentQuery.data?.full_name ?? null;
  useEffect(() => {
    const previous = document.title;
    document.title = studentDocumentTitle(studentName);
    return () => {
      document.title = previous;
    };
  }, [studentName]);

  if (!studentId) {
    return (
      <section className="space-y-4">
        <BackLink />
        <Card p={20}>
          <p className="text-sm text-rally-muted">Missing student id.</p>
        </Card>
      </section>
    );
  }

  if (studentQuery.isPending) {
    return (
      <section className="space-y-4">
        <BackLink />
        <Card p={20}>
          <div
            className="h-24 animate-pulse rounded-lg bg-neutral-100 dark:bg-neutral-800"
            aria-label="Loading student"
          />
        </Card>
      </section>
    );
  }

  if (studentQuery.isError) {
    return (
      <section className="space-y-4">
        <BackLink />
        <Card p={20}>
          <p role="alert" className="text-sm text-red-700">
            Could not load student.
          </p>
        </Card>
      </section>
    );
  }

  const student = studentQuery.data;
  if (!student) {
    return (
      <section className="space-y-4">
        <BackLink />
        <Card p={20}>
          <p className="text-sm text-rally-muted">Student not found.</p>
        </Card>
      </section>
    );
  }

  return (
    <section
      className="space-y-6"
      data-testid="admin-student-detail"
      data-student-id={student.student_id}
    >
      <BackLink />
      <Header
        student={student}
        onStopAllClasses={() => setStopAllClassesOpen(true)}
      />
      {stopAllClassesOpen && (
        <StopAllClassesDialog
          studentId={student.student_id}
          studentName={student.full_name}
          policyDefaultOutcome={departurePolicyQuery.data?.drop_default_outcome}
          onClose={() => setStopAllClassesOpen(false)}
          onDone={() => {
            void queryClient.invalidateQueries({
              queryKey: queryKeys.admin.studentDetail(studentId),
            });
          }}
        />
      )}
      <StudentSummaryStrip student={student} />
      <StudentTabs activeTab={activeTab} onChange={selectTab} />

      {activeTab === "overview" && (
        <TabPanel id="overview">
          <div className="grid gap-6 lg:grid-cols-[minmax(0,1.7fr)_minmax(280px,0.8fr)]">
            <Card p={20}>
              <div className="flex items-center gap-2">
                <UserRound className="size-4 text-rally-muted" aria-hidden="true" />
                <Overline>Profile</Overline>
              </div>
              <StudentEditForm
                mode="overview"
                student={student}
                onSaved={() => {
                  void queryClient.invalidateQueries({
                    queryKey: queryKeys.admin.studentDetail(studentId),
                  });
                  void queryClient.invalidateQueries({
                    queryKey: ["admin", "students"],
                  });
                }}
              />
            </Card>
            <EngagementPanel student={student} />
          </div>
        </TabPanel>
      )}

      {activeTab === "training" && (
        <TabPanel id="training">
          <div
            className="grid gap-6 lg:grid-cols-[minmax(0,1.3fr)_minmax(340px,0.9fr)]"
            data-testid="admin-student-training-tab"
          >
            <Card p={20}>
              <div className="flex items-center gap-2">
                <Activity className="size-4 text-rally-muted" aria-hidden="true" />
                <Overline>Training details</Overline>
              </div>
              <TrainingSnapshot student={student} />
              <StudentEditForm
                mode="training"
                student={student}
                onSaved={() => {
                  void queryClient.invalidateQueries({
                    queryKey: queryKeys.admin.studentDetail(studentId),
                  });
                  void queryClient.invalidateQueries({
                    queryKey: ["admin", "students"],
                  });
                }}
              />
            </Card>
            <div className="space-y-6">
              <SkillPathwayPanel student={student} />
              <RecentAttendancePanel student={student} />
            </div>
          </div>
        </TabPanel>
      )}

      {activeTab === "sessions" && (
        <TabPanel id="sessions">
          <SessionsPanel
            sessions={student.enrolled_sessions ?? []}
            pastEnrollments={student.past_enrollments ?? []}
            parentId={student.parent_id}
            studentId={studentId}
            studentName={student.full_name}
            queryClient={queryClient}
          />
        </TabPanel>
      )}

      {activeTab === "billing" && (
        <TabPanel id="billing">
          <div className="space-y-6">
            <FamilyBillingLink parentId={student.parent_id} parentName={student.parent_name} />
            <BillingEnrollmentsPanel studentId={studentId} active={activeTab === "billing"} />
          </div>
        </TabPanel>
      )}

      {activeTab === "family" && (
        <TabPanel id="family">
          <div
            className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(340px,1fr)]"
            data-testid="admin-student-compliance-tab"
          >
            <Card p={20}>
              <div className="flex items-center gap-2">
                <ShieldCheck className="size-4 text-rally-muted" aria-hidden="true" />
                <Overline>Family & compliance</Overline>
              </div>
              <ComplianceSummary student={student} />
              <StudentEditForm
                mode="family"
                student={student}
                onSaved={() => {
                  void queryClient.invalidateQueries({
                    queryKey: queryKeys.admin.studentDetail(studentId),
                  });
                  void queryClient.invalidateQueries({
                    queryKey: ["admin", "students"],
                  });
                }}
              />
            </Card>
            <Card p={20}>
              <Overline>Parent account</Overline>
              <ChangeParentPanel
                student={student}
                parents={parentsQuery.data?.users ?? []}
                parentsLoading={parentsQuery.isLoading}
                parentsError={parentsQuery.isError}
                onSaved={() => {
                  void queryClient.invalidateQueries({
                    queryKey: queryKeys.admin.studentDetail(studentId),
                  });
                  void queryClient.invalidateQueries({
                    queryKey: ["admin", "students"],
                  });
                  void queryClient.invalidateQueries({
                    queryKey: queryKeys.admin.users("parent"),
                  });
                }}
              />
            </Card>
          </div>
        </TabPanel>
      )}
    </section>
  );
}

function StudentSummaryStrip({ student }: { student: AdminStudentDetail }) {
  const outstandingBalance =
    student.outstanding_balance_cents ??
    student.payment_history.reduce(
      (sum, payment) =>
        OPEN_BILLING_STATUSES.has(payment.status) ? sum + Math.max(payment.balance_due_cents, 0) : sum,
      0,
    );
  const unpaidInvoiceCount = student.payment_history.filter(
    (payment) => OPEN_BILLING_STATUSES.has(payment.status) && payment.balance_due_cents > 0,
  ).length;
  const attendance =
    student.attendance_rate == null
      ? "—"
      : `${Math.round(Math.max(0, Math.min(student.attendance_rate, 1)) * 100)}%`;

  return (
    // #897: below `sm` this was one column, so four ~110px cards stacked
    // between the header and the tabs and pushed the tabs off a 400x860
    // first screen. Two-up on a phone, unchanged from `sm` up.
    <div
      className="grid grid-cols-2 gap-3 sm:grid-cols-2 xl:grid-cols-4"
      data-testid="admin-student-summary-strip"
    >
      <SummaryMetric
        icon={<CalendarCheck className="size-4" aria-hidden="true" />}
        label="Active sessions"
        value={String(student.active_session_count)}
        detail={
          student.last_seen_at
            ? `Last attended ${formatDate(student.last_seen_at)}`
            : "No attendance yet"
        }
      />
      <SummaryMetric
        icon={<Activity className="size-4" aria-hidden="true" />}
        label="Attendance"
        value={attendance}
        detail="Last 30 days"
      />
      <SummaryMetric
        icon={<Wallet className="size-4" aria-hidden="true" />}
        label="Outstanding balance"
        value={formatCurrencyCents(outstandingBalance)}
        detail={
          unpaidInvoiceCount === 0
            ? "No unpaid invoices"
            : `${unpaidInvoiceCount} unpaid ${unpaidInvoiceCount === 1 ? "invoice" : "invoices"}`
        }
      />
      <SummaryMetric
        icon={<FileCheck className="size-4" aria-hidden="true" />}
        label="Waiver"
        value={(student.waiver_status ?? "unknown").toUpperCase()}
        detail={student.waiver_version ?? "No version on file"}
      />
    </div>
  );
}

function SummaryMetric({
  icon,
  label,
  value,
  detail,
}: {
  icon: ReactNode;
  label: string;
  value: string;
  detail: string;
}) {
  return (
    <div className="rounded-lg border border-neutral-200 bg-white p-3 sm:p-4">
      <div className="flex items-center gap-2 text-rally-muted">
        {icon}
        <span className="font-mono text-[10px] font-bold uppercase tracking-overline">
          {label}
        </span>
      </div>
      {/* #896: the figure is a display numeral (Outfit), not a code token —
          only the label above it stays mono, as an Overline caption. */}
      <div className="mt-2 font-display text-2xl font-semibold tabular-nums text-rally-ink sm:mt-3">
        {value}
      </div>
      <div className="mt-1 truncate text-xs text-rally-muted">{detail}</div>
    </div>
  );
}

function StudentTabs({
  activeTab,
  onChange,
}: {
  activeTab: StudentTab;
  onChange: (tab: StudentTab) => void;
}) {
  return (
    <div
      role="tablist"
      aria-label="Student record sections"
      data-testid="admin-student-tabs"
      className="flex gap-1 overflow-x-auto border-b border-neutral-200"
    >
      {STUDENT_TABS.map((tab) => {
        const selected = activeTab === tab.id;
        return (
          <button
            key={tab.id}
            type="button"
            role="tab"
            aria-selected={selected}
            aria-controls={`student-tabpanel-${tab.id}`}
            id={`student-tab-${tab.id}`}
            className={`whitespace-nowrap border-b-2 px-3 py-2 text-sm font-medium transition-colors focus:outline-none focus:ring-2 focus:ring-rally-cobalt-600 ${
              selected
                ? "border-rally-cobalt-600 text-rally-ink"
                : "border-transparent text-rally-muted hover:text-rally-ink"
            }`}
            onClick={() => onChange(tab.id)}
          >
            {tab.label}
          </button>
        );
      })}
    </div>
  );
}

function TabPanel({
  id,
  children,
}: {
  id: StudentTab;
  children: ReactNode;
}) {
  return (
    <div
      role="tabpanel"
      id={`student-tabpanel-${id}`}
      aria-labelledby={`student-tab-${id}`}
      className="min-w-0"
    >
      {children}
    </div>
  );
}

function EngagementPanel({ student }: { student: AdminStudentDetail }) {
  return (
    <Card p={20}>
      <div className="flex items-center gap-2">
        <Activity className="size-4 text-rally-muted" aria-hidden="true" />
        <Overline>Engagement</Overline>
      </div>
      <DetailList
        rows={[
          {
            label: "Active sessions",
            value: String(student.active_session_count),
          },
          {
            label: "Attendance (30d)",
            value:
              student.attendance_rate == null
                ? "—"
                : `${Math.round(Math.max(0, Math.min(student.attendance_rate, 1)) * 100)}%`,
          },
          {
            label: "Last attended",
            value: student.last_seen_at ? formatDate(student.last_seen_at) : "—",
          },
          {
            label: "Dues",
            value: student.dues_status.toUpperCase(),
          },
        ]}
      />
    </Card>
  );
}

function TrainingSnapshot({ student }: { student: AdminStudentDetail }) {
  const academyId = getActiveAcademyId() ?? "";
  const { data: programs } = useQuery({
    queryKey: ["admin", "programs", academyId],
    queryFn: () => listPrograms(academyId),
    enabled: Boolean(academyId),
  });
  // TODO: derive programId from student.enrolled_sessions once AdminStudentSessionSummary
  // exposes pathway_program_id — for now fall back to programs[0]
  const programId = programs?.[0]?.program_id ?? "";
  const { data: progress } = useQuery({
    queryKey: ["admin", "student-progress", student.student_id, programId],
    queryFn: () => getStudentProgress(student.student_id, programId),
    enabled: Boolean(programId),
  });

  return (
    <div className="mt-3 rounded-lg border border-neutral-200 bg-neutral-50 p-3 text-sm">
      <div className="font-medium text-rally-ink">Skill pathway placement</div>
      {progress?.current_level_name ? (
        <>
          <p className="mt-1 text-rally-muted">
            Level {progress.current_level_sequence}: {progress.current_level_name}
          </p>
          <p className="mt-0.5 text-xs text-rally-muted">
            {progress.passed_skills} / {progress.total_skills} skills passed
          </p>
        </>
      ) : (
        <p className="mt-1 text-rally-muted">Not placed in a level yet.</p>
      )}
    </div>
  );
}

function SkillPathwayPanel({ student }: { student: AdminStudentDetail }) {
  return (
    <Card p={20}>
      <div className="flex items-center gap-2">
        <Activity className="size-4 text-rally-muted" aria-hidden="true" />
        <Overline>Skill pathway</Overline>
      </div>
      <p className="mt-3 text-sm text-rally-muted">
        Place this student in a curriculum level and review skill completion.
      </p>
      <div className="mt-4">
        <Link
          href={buildStudentProgressHref({
            studentId: student.student_id,
            returnTo: `/admin/students/${encodeURIComponent(student.student_id)}`,
            returnLabel: "Back to student profile",
          }) as Parameters<typeof Link>[0]["href"]}
          className="inline-flex items-center justify-center rounded-md bg-blue-600 px-3 py-2 text-sm font-semibold text-white transition-colors hover:bg-blue-700"
        >
          Manage skill progress
        </Link>
      </div>
    </Card>
  );
}

function RecentAttendancePanel({ student }: { student: AdminStudentDetail }) {
  const recent = student.recent_attendance ?? [];

  return (
    <Card p={20}>
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <CalendarCheck className="size-4 text-rally-muted" aria-hidden="true" />
          <Overline>Recent attendance</Overline>
        </div>
        <span className="font-mono text-xs text-rally-muted tabular-nums">
          {recent.length} records
        </span>
      </div>
      {recent.length === 0 ? (
        <p className="mt-3 text-sm text-rally-muted">
          No attendance records yet.
        </p>
      ) : (
        <div
          className="mt-3 overflow-x-auto"
          data-testid="admin-student-recent-attendance"
        >
          <table className="min-w-full text-left text-sm">
            <thead className="border-b border-neutral-200 text-xs uppercase tracking-overline text-rally-muted">
              <tr>
                <th className="py-2 pr-4 font-medium">Date</th>
                <th className="py-2 pr-4 font-medium">Status</th>
                <th className="py-2 font-medium">Marked</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-neutral-100">
              {recent.map((entry) => (
                <tr key={`${entry.session_id}-${entry.date}-${entry.status}`}>
                  <td className="py-3 pr-4 align-top text-rally-ink">
                    {formatDateUtc(entry.date)}
                  </td>
                  <td className="py-3 pr-4 align-top">
                    <StatusChip status={entry.status} />
                  </td>
                  <td className="py-3 align-top text-rally-muted">
                    {formatDateTime(entry.marked_at)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}

function ComplianceSummary({ student }: { student: AdminStudentDetail }) {
  return (
    <DetailList
      rows={[
        {
          label: "Waiver status",
          value: (student.waiver_status ?? "unknown").toUpperCase(),
        },
        {
          label: "Waiver version",
          value: student.waiver_version ?? "—",
        },
        {
          label: "Signed at",
          value: formatDateTime(student.waiver_signed_at),
        },
        {
          label: "Parent",
          value: student.parent_name ?? student.parent_email ?? "—",
        },
      ]}
    />
  );
}

function BackLink() {
  return (
    <Link
      href="/admin/students"
      className="inline-flex items-center gap-1.5 text-sm text-rally-muted hover:text-rally-ink focus:outline-none focus:ring-2 focus:ring-rally-cobalt-600 rounded"
    >
      <ArrowLeft className="size-4" aria-hidden="true" />
      <span>All students</span>
    </Link>
  );
}

function Header({
  student,
  onStopAllClasses,
}: {
  student: AdminStudentDetail;
  onStopAllClasses: () => void;
}) {
  return (
    <Card p={20}>
      {/* #897: on a phone "Stop all classes" sat directly beside the parent's
          tel:/mailto: links, one mis-tap from ending every enrollment. It is
          now an actions menu pinned to the card's top-right; the dialog and
          everything it does are unchanged.
          On a phone the menu shares the name row and the parent's contacts
          take the card's full width: beside the menu they wrapped WhatsApp
          onto a third 44px row at 390px (iPhone 14), which pushed the tabs
          below the fold. From `sm` up it is one row, as before. */}
      <div className="grid grid-cols-[minmax(0,1fr)_auto] items-start gap-x-3 gap-y-4 sm:flex sm:items-center">
          <div className="flex min-w-0 items-center gap-4">
            <Avatar name={student.full_name} size={56} />
            <div className="min-w-0">
              <h2 className="truncate font-display text-xl font-semibold tracking-[-0.01em] text-rally-ink">
                {student.full_name}
              </h2>
              <div className="mt-1 flex items-center gap-2">
                {/* Issue #773: the derived lifecycle, with its date. */}
                {lifecycleLabel(student.lifecycle, student.lifecycle_as_of) && (
                  <Chip
                    variant={lifecycleVariant(student.lifecycle)}
                    label={lifecycleLabel(student.lifecycle, student.lifecycle_as_of)}
                  />
                )}
              </div>
            </div>
          </div>
          <div className="col-span-2 text-sm text-rally-muted sm:ml-auto">
            {/* #839: the parent was plain text here, so the family — and every
                invoice on it — was two clicks away via the Billing tab. */}
            {student.parent_id ? (
              <Link
                href={`/admin/families/${encodeURIComponent(student.parent_id)}`}
                className="block rounded font-medium text-rally-ink hover:underline focus:outline-none focus:ring-2 focus:ring-rally-cobalt-600"
                data-testid="admin-student-parent-link"
              >
                {student.parent_name ?? student.parent_email ?? "Parent on file"}
              </Link>
            ) : (
              <div className="font-medium text-rally-ink">
                {student.parent_name ?? student.parent_email ?? "Parent on file"}
              </div>
            )}
            {/* #865: the one place that already had a `tel:`, now through the
                shared component — so it gains WhatsApp with everywhere else. */}
            <ContactLinks
              data-testid="admin-student-parent-contacts"
              name={student.parent_name ?? undefined}
              email={student.parent_email}
              phone={student.parent_phone}
            />
          </div>
        <OverflowMenu
          className="col-start-2 row-start-1 shrink-0 sm:self-start"
          triggerLabel={`Actions for ${student.full_name}`}
          triggerTestId="admin-student-actions"
          items={[
            {
              key: "stop-all-classes",
              label: "Stop all classes",
              description: "Ends every enrollment on the date you pick.",
              danger: true,
              onSelect: onStopAllClasses,
            },
          ]}
          trigger={
            <span className="flex min-h-touch min-w-touch items-center justify-center rounded-md text-rally-muted hover:bg-rally-paper">
              <MoreVertical className="size-5" aria-hidden="true" />
            </span>
          }
        />
      </div>
    </Card>
  );
}

