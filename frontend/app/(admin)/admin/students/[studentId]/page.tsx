"use client";

/**
 * Admin student detail page.
 *
 * Pulls a single student from the v2 BFF and exposes safe admin-editable
 * fields. No raw internal ids are rendered in normal UI.
 */

import { type ReactNode, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Activity,
  ArrowLeft,
  Ban,
  CalendarCheck,
  CreditCard,
  DollarSign,
  FileCheck,
  FilePlus2,
  Plus,
  RefreshCw,
  Send,
  ShieldCheck,
  Trash2,
  UserRound,
  Wallet,
} from "lucide-react";

import {
  addAdminInvoiceLine,
  chargeAdminInvoiceAutopay,
  changeAdminStudentParent,
  deleteAdminInvoiceLine,
  getAdminInvoiceDetail,
  listAdminSessions,
  listAdminUsers,
  listBillingProducts,
  recordAdminInvoicePayment,
  sendAdminInvoice,
  voidAdminInvoice,
  type AdminBillingProductView,
  type AdminInvoiceDetail,
  type AddInvoiceLineRequest,
  type AdminSessionView,
  type AdminUserView,
  type ChangeAdminStudentParentRequest,
  type RecordManualPaymentRequest,
} from "@/lib/api/admin";
import {
  createAdminStudentInvoice,
  getAdminStudent,
  overrideEnrollmentFee,
  removeTuitionDiscount,
  setTuitionDiscount,
  transferEnrollment,
  updateAdminStudent,
  type AdminStudentDetail,
  type AdminStudentPaymentSummary,
  type AdminStudentSessionSummary,
  type TuitionDiscountCategory,
  type TuitionDiscountKind,
  type UpdateAdminStudentRequest,
} from "@/lib/api/v2/students";
import { getActiveAcademyId } from "@/lib/api/client";
import { getStudentProgress, listPrograms } from "@/lib/api/curriculum";
import { buildStudentProgressHref } from "@/lib/navigation/admin-student-progress-return";
import { queryKeys } from "@/lib/query/keys";
import {
  StudentDetailTabs,
  parseStudentDetailTabId,
  type StudentDetailTabId,
} from "@/components/admin/StudentDetailTabs";
import { Avatar } from "@/components/ds/avatar";
import { Button } from "@/components/ds/button";
import { Card } from "@/components/ds/card";
import { Chip } from "@/components/ds/chip";
import { Overline } from "@/components/ds/typography";

type EditableStatus = "active" | "paused" | "inactive" | "cancelled";
type StudentTab = StudentDetailTabId;
type StudentEditMode = "overview" | "training" | "family";
type BillingModal = "add-line" | "manual-payment" | "void" | "create-invoice" | null;

const OPEN_BILLING_STATUSES = new Set([
  "open",
  "unpaid",
  "partially_paid",
  "partial",
  "pending",
  "failed",
  "expired",
]);

export default function AdminStudentDetailPage() {
  const params = useParams<{ studentId: string }>();
  const studentId = params?.studentId ?? "";
  const searchParams = useSearchParams();
  const queryClient = useQueryClient();
  const [activeTab, setActiveTab] = useState<StudentTab>(
    parseStudentDetailTabId(searchParams.get("tab")),
  );

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
      <Header student={student} />
      <StudentSummaryStrip student={student} />
      <StudentDetailTabs studentId={studentId} active={activeTab} onChangeTab={setActiveTab} />

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
            studentId={studentId}
            queryClient={queryClient}
          />
        </TabPanel>
      )}

      {activeTab === "billing" && (
        <TabPanel id="billing">
          <BillingWorkflowPanel
            student={student}
            active={activeTab === "billing"}
            onChanged={() => {
              void queryClient.invalidateQueries({
                queryKey: queryKeys.admin.studentDetail(studentId),
              });
            }}
          />
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
    <div
      className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4"
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
    <div className="rounded-lg border border-neutral-200 bg-white p-4">
      <div className="flex items-center gap-2 text-rally-muted">
        {icon}
        <span className="font-mono text-[10px] font-bold uppercase tracking-overline">
          {label}
        </span>
      </div>
      <div className="mt-3 font-mono text-2xl font-semibold tabular-nums text-rally-ink">
        {value}
      </div>
      <div className="mt-1 truncate text-xs text-rally-muted">{detail}</div>
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
                    {formatDate(entry.date)}
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

function BillingWorkflowPanel({
  student,
  active,
  onChanged,
}: {
  student: AdminStudentDetail;
  active: boolean;
  onChanged: () => void;
}) {
  const current = student.current_payment;
  const invoiceRows = useMemo(() => student.payment_history ?? [], [student.payment_history]);
  const [createdInvoiceId, setCreatedInvoiceId] = useState<string | null>(null);
  const [selectedInvoiceId, setSelectedInvoiceId] = useState<string | null>(null);
  const defaultInvoiceId =
    createdInvoiceId ??
    current?.payment_id ??
    invoiceRows.find(
      (row) => OPEN_BILLING_STATUSES.has(row.status) && row.balance_due_cents > 0,
    )?.payment_id ??
    invoiceRows[0]?.payment_id ??
    null;
  const invoiceIds = useMemo(
    () =>
      new Set([
        ...invoiceRows.map((row) => row.payment_id),
        ...(createdInvoiceId ? [createdInvoiceId] : []),
      ]),
    [createdInvoiceId, invoiceRows],
  );
  useEffect(() => {
    if (!active) return;
    if (selectedInvoiceId && invoiceIds.has(selectedInvoiceId)) return;
    setSelectedInvoiceId(defaultInvoiceId);
  }, [active, defaultInvoiceId, invoiceIds, selectedInvoiceId]);

  const invoiceId = selectedInvoiceId ?? defaultInvoiceId;
  const selectedSummary = invoiceRows.find((row) => row.payment_id === invoiceId) ?? null;
  const outstandingBalance =
    student.outstanding_balance_cents ??
    invoiceRows.reduce(
      (sum, payment) =>
        OPEN_BILLING_STATUSES.has(payment.status)
          ? sum + Math.max(payment.balance_due_cents, 0)
          : sum,
      0,
    );
  const unpaidInvoiceCount = invoiceRows.filter(
    (payment) => OPEN_BILLING_STATUSES.has(payment.status) && payment.balance_due_cents > 0,
  ).length;
  const [modal, setModal] = useState<BillingModal>(null);
  const [actionMessage, setActionMessage] = useState<string | null>(null);

  const invoiceQuery = useQuery({
    queryKey: ["admin", "billing", "invoice", invoiceId],
    queryFn: () => getAdminInvoiceDetail(invoiceId!),
    enabled: active && Boolean(invoiceId),
  });
  const productsQuery = useQuery({
    queryKey: ["admin", "billing", "products"],
    queryFn: () => listBillingProducts(),
    enabled: active && modal === "add-line",
  });

  const invoice = invoiceQuery.data;
  const status = invoice?.status ?? selectedSummary?.status ?? current?.status ?? "draft";
  const balanceDueCents =
    invoice?.balance_due_cents ??
    invoice?.due_amount_cents ??
    selectedSummary?.balance_due_cents ??
    current?.amount_cents ??
    0;
  const invoiceTotalCents =
    invoice?.total_cents ??
    (invoice
      ? invoice.due_amount_cents + invoice.paid_amount_cents
      : selectedSummary?.amount_cents ?? current?.amount_cents ?? 0);
  const paidAmountCents = invoice?.paid_amount_cents ?? selectedSummary?.paid_amount_cents ?? 0;
  const isDraft = status === "draft";
  const isVoid = status === "void";
  const isPaid = status === "paid";
  const canVoid = (status === "draft" || status === "open") && balanceDueCents === invoiceTotalCents;
  const canAddLines = Boolean(invoiceId) && !isVoid && !isPaid;
  const canRemoveLines = Boolean(invoiceId) && isDraft;
  const canSend = Boolean(invoiceId) && !isVoid && !isPaid;
  const canRecordPayment = Boolean(invoiceId) && !isDraft && !isVoid && balanceDueCents > 0;
  const canChargeAutopay = canRecordPayment;

  const refreshInvoice = () => {
    if (invoiceId) {
      void invoiceQuery.refetch();
    }
    onChanged();
  };

  const sendMutation = useMutation({
    mutationFn: () => sendAdminInvoice(invoiceId!),
    onSuccess: (result) => {
      setActionMessage(
        result.delivery_status === "sent" && result.checkout_url
          ? `Invoice sent. Checkout link: ${result.checkout_url}`
          : result.delivery_status === "sent"
            ? "Invoice sent."
            : result.checkout_url
              ? `Checkout link generated: ${result.checkout_url}`
              : "Invoice delivery is not configured.",
      );
      refreshInvoice();
    },
  });

  const chargeMutation = useMutation({
    mutationFn: () => chargeAdminInvoiceAutopay(invoiceId!),
    onSuccess: (result) => {
      setActionMessage(
        result.success
          ? "Card charged successfully."
          : result.requires_action
            ? "Card requires parent action (3-D Secure verification)."
            : `Charge did not complete: ${result.status}`,
      );
      refreshInvoice();
    },
  });

  const deleteLineMutation = useMutation({
    mutationFn: (lineId: string) => deleteAdminInvoiceLine(invoiceId!, lineId),
    onSuccess: () => {
      setActionMessage("Line item removed.");
      refreshInvoice();
    },
  });

  const createInvoiceMutation = useMutation({
    mutationFn: (payload: { period: string; due_date: string; enrollment_id?: string | null }) =>
      createAdminStudentInvoice(student.student_id, {
        parent_id: student.parent_id,
        period: payload.period,
        due_date: payload.due_date,
        enrollment_id: payload.enrollment_id ?? null,
      }),
    onSuccess: (newInvoice) => {
      setCreatedInvoiceId(newInvoice.invoice_id);
      setSelectedInvoiceId(newInvoice.invoice_id);
      setModal(null);
      setActionMessage("Draft invoice created.");
      onChanged();
    },
  });

  const errorMessage =
    getErrorMessage(sendMutation.error) ??
    getErrorMessage(chargeMutation.error) ??
    getErrorMessage(deleteLineMutation.error) ??
    getErrorMessage(createInvoiceMutation.error) ??
    getErrorMessage(invoiceQuery.error);

  return (
    <>
      <Card p={20} data-testid="admin-student-billing-workflow">
        <div
          className="flex flex-col gap-4 border-b border-neutral-200 pb-5 lg:flex-row lg:items-start lg:justify-between"
          data-testid="admin-student-account-balance"
        >
          <div>
            <div className="flex items-center gap-2">
              <Wallet className="size-4 text-rally-muted" aria-hidden="true" />
              <Overline>Account balance</Overline>
            </div>
            <div className="mt-2 font-mono text-3xl font-semibold tabular-nums text-rally-ink">
              {formatCurrencyCents(outstandingBalance)}
            </div>
            <p className="mt-1 text-sm text-rally-muted">
              {unpaidInvoiceCount === 0
                ? "No unpaid invoices"
                : `${unpaidInvoiceCount} unpaid ${unpaidInvoiceCount === 1 ? "invoice" : "invoices"}`}
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button
              size="sm"
              icon={<FilePlus2 className="size-3.5" aria-hidden="true" />}
              onClick={() => setModal("create-invoice")}
            >
              Create invoice
            </Button>
          </div>
        </div>

        {errorMessage && (
          <p role="alert" className="mt-3 rounded-md bg-red-50 px-3 py-2 text-xs text-red-700">
            {errorMessage}
          </p>
        )}
        {actionMessage && (
          <p className="mt-3 break-words rounded-md bg-blue-50 px-3 py-2 text-xs text-blue-800">
            {actionMessage}
          </p>
        )}

        <div className="mt-5 grid gap-5 lg:grid-cols-[minmax(260px,0.75fr)_minmax(0,1.45fr)]">
          <StudentInvoiceList
            invoices={invoiceRows}
            selectedInvoiceId={invoiceId}
            onSelect={(nextInvoiceId) => {
              setSelectedInvoiceId(nextInvoiceId);
              setActionMessage(null);
            }}
          />

          <section className="min-w-0" data-testid="admin-student-selected-invoice">
            <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
              <div className="flex items-center gap-2">
                <CreditCard className="size-4 text-rally-muted" aria-hidden="true" />
                <Overline>Selected invoice</Overline>
              </div>
              {invoiceId && (
                <div className="flex flex-wrap gap-2">
                  <Button
                    size="sm"
                    variant="secondary"
                    icon={<Plus className="size-3.5" aria-hidden="true" />}
                    onClick={() => setModal("add-line")}
                    disabled={!canAddLines}
                    title={!canAddLines ? "Paid or void invoices cannot be edited." : undefined}
                  >
                    Add charge
                  </Button>
                  <Button
                    size="sm"
                    variant="secondary"
                    icon={
                      sendMutation.isPending ? (
                        <RefreshCw className="size-3.5 animate-spin" aria-hidden="true" />
                      ) : (
                        <Send className="size-3.5" aria-hidden="true" />
                      )
                    }
                    onClick={() => sendMutation.mutate()}
                    disabled={!canSend || sendMutation.isPending}
                  >
                    Send
                  </Button>
                  <Button
                    size="sm"
                    variant="secondary"
                    icon={<DollarSign className="size-3.5" aria-hidden="true" />}
                    onClick={() => setModal("manual-payment")}
                    disabled={!canRecordPayment}
                    title={isDraft ? "Send the invoice before recording payment." : undefined}
                  >
                    Record payment
                  </Button>
                  <Button
                    size="sm"
                    variant="secondary"
                    icon={
                      chargeMutation.isPending ? (
                        <RefreshCw className="size-3.5 animate-spin" aria-hidden="true" />
                      ) : (
                        <CreditCard className="size-3.5" aria-hidden="true" />
                      )
                    }
                    onClick={() => chargeMutation.mutate()}
                    disabled={!canChargeAutopay || chargeMutation.isPending}
                    title={
                      isDraft
                        ? "Send the invoice before charging the card."
                        : "Charge the parent's saved card now (requires a card on file)."
                    }
                  >
                    Charge card
                  </Button>
                  <Button
                    size="sm"
                    variant="danger"
                    icon={<Ban className="size-3.5" aria-hidden="true" />}
                    onClick={() => setModal("void")}
                    disabled={!canVoid}
                    title={
                      !canVoid ? "Invoices with recorded payments cannot be voided here." : undefined
                    }
                  >
                    Void
                  </Button>
                </div>
              )}
            </div>

            {!invoiceId ? (
              <p
                className="mt-4 text-sm text-rally-muted"
                data-testid="admin-student-no-current-payment"
              >
                No invoice selected.
              </p>
            ) : (
              <div className="mt-4 space-y-5" data-testid="admin-student-current-payment">
                <div className="grid gap-3 md:grid-cols-4">
                  <InvoiceMetric label="Total" value={formatCurrencyCents(invoiceTotalCents)} />
                  <InvoiceMetric label="Paid" value={formatCurrencyCents(paidAmountCents)} />
                  <InvoiceMetric label="Balance" value={formatCurrencyCents(balanceDueCents)} />
                  <div className="rounded-lg border border-neutral-200 bg-neutral-50 p-3">
                    <div className="font-mono text-[10px] font-bold uppercase tracking-overline text-rally-muted">
                      Status
                    </div>
                    <div className="mt-2">
                      <StatusChip status={status} />
                    </div>
                  </div>
                </div>

                <DetailList
                  rows={[
                    {
                      label: "Invoice",
                      value: invoice?.invoice_number ?? selectedSummary?.invoice_number ?? invoiceId,
                    },
                    { label: "Period", value: invoice?.period ?? selectedSummary?.period ?? "—" },
                    { label: "Delivery", value: invoice?.delivery_status ?? "not_sent" },
                    { label: "Sent", value: formatDateTime(invoice?.last_sent_at ?? invoice?.sent_at) },
                    {
                      label: "Session",
                      value:
                        selectedSummary?.session_id ??
                        current?.session_title ??
                        current?.session_id ??
                        "—",
                    },
                  ]}
                />

                {invoice?.email_provider_message_id ? (
                  <a
                    href={`https://resend.com/emails/${invoice.email_provider_message_id}`}
                    target="_blank"
                    rel="noopener noreferrer"
                    data-testid="admin-invoice-resend-link"
                    className="inline-flex items-center gap-1 text-xs font-medium text-rally-primary underline underline-offset-2 hover:opacity-80"
                  >
                    View delivery in Resend ↗
                  </a>
                ) : null}

                {invoiceQuery.isPending ? (
                  <div
                    className="h-20 animate-pulse rounded-lg bg-neutral-100"
                    aria-label="Loading invoice"
                  />
                ) : (
                  <InvoiceLinesTable
                    invoice={invoice}
                    canRemove={canRemoveLines}
                    removingLineId={
                      deleteLineMutation.isPending ? (deleteLineMutation.variables ?? null) : null
                    }
                    onRemove={(lineId) => deleteLineMutation.mutate(lineId)}
                  />
                )}

                <InvoiceSettlementPanel invoice={invoice} />
              </div>
            )}
          </section>
        </div>
      </Card>

      {modal === "create-invoice" && (
        <CreateInvoiceDialog
          student={student}
          pending={createInvoiceMutation.isPending}
          error={getErrorMessage(createInvoiceMutation.error)}
          onCancel={() => setModal(null)}
          onSubmit={(payload) => createInvoiceMutation.mutate(payload)}
        />
      )}
      {modal === "add-line" && invoiceId && (
        <AddInvoiceLineDialog
          invoiceId={invoiceId}
          products={productsQuery.data?.products ?? []}
          productsLoading={productsQuery.isPending}
          onCancel={() => setModal(null)}
          onSaved={(payload) => addAdminInvoiceLine(invoiceId, payload)}
          onDone={() => {
            setModal(null);
            setActionMessage("Line item added.");
            refreshInvoice();
          }}
        />
      )}
      {modal === "manual-payment" && invoiceId && (
        <RecordPaymentDialog
          balanceDueCents={balanceDueCents}
          onCancel={() => setModal(null)}
          onSaved={(payload) => recordAdminInvoicePayment(invoiceId, payload)}
          onDone={(paymentId) => {
            setModal(null);
            setActionMessage(`Payment recorded: ${paymentId}`);
            refreshInvoice();
          }}
        />
      )}
      {modal === "void" && invoiceId && (
        <VoidInvoiceDialog
          onCancel={() => setModal(null)}
          onSaved={(reason) => voidAdminInvoice(invoiceId, { reason })}
          onDone={() => {
            setModal(null);
            setActionMessage("Invoice voided.");
            refreshInvoice();
          }}
        />
      )}
    </>
  );
}

function StudentInvoiceList({
  invoices,
  selectedInvoiceId,
  onSelect,
}: {
  invoices: AdminStudentPaymentSummary[];
  selectedInvoiceId: string | null;
  onSelect: (invoiceId: string) => void;
}) {
  return (
    <section className="min-w-0" data-testid="admin-student-invoice-list">
      <div className="flex items-center justify-between gap-3">
        <Overline>Invoices</Overline>
        <span className="font-mono text-xs text-rally-muted tabular-nums">
          {invoices.length} records
        </span>
      </div>
      {invoices.length === 0 ? (
        <p className="mt-4 text-sm text-rally-muted" data-testid="admin-student-no-payments">
          No invoice records.
        </p>
      ) : (
        <div className="mt-3 divide-y divide-neutral-100 border-y border-neutral-200">
          {invoices.map((invoice) => {
            const selected = invoice.payment_id === selectedInvoiceId;
            const payable =
              OPEN_BILLING_STATUSES.has(invoice.status) && invoice.balance_due_cents > 0;
            return (
              <button
                key={invoice.payment_id}
                type="button"
                aria-pressed={selected}
                onClick={() => onSelect(invoice.payment_id)}
                className={[
                  "grid w-full grid-cols-[minmax(0,1fr)_auto] gap-3 px-2 py-3 text-left transition",
                  "hover:bg-neutral-50 focus:outline-none focus:ring-2 focus:ring-rally-cobalt-600",
                  selected ? "bg-blue-50" : "bg-white",
                ].join(" ")}
              >
                <span className="min-w-0">
                  <span className="block truncate text-sm font-medium text-rally-ink">
                    {invoice.invoice_number ?? `Invoice ${invoice.period ?? invoice.payment_id}`}
                  </span>
                  <span className="mt-1 block text-xs text-rally-muted">
                    {invoice.period ?? "No period"} · Created {formatDate(invoice.created_at)}
                  </span>
                  {payable && (
                    <span className="mt-1 block text-xs text-rally-muted">
                      Unpaid balance {formatCurrencyCents(invoice.balance_due_cents)}
                    </span>
                  )}
                </span>
                <span className="flex flex-col items-end gap-2">
                  <StatusChip status={invoice.status} />
                  <span className="font-mono text-sm tabular-nums text-rally-ink">
                    {formatCurrencyCents(invoice.balance_due_cents)}
                  </span>
                </span>
              </button>
            );
          })}
        </div>
      )}
    </section>
  );
}

function InvoiceMetric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-neutral-200 bg-neutral-50 p-3">
      <div className="font-mono text-[10px] font-bold uppercase tracking-overline text-rally-muted">
        {label}
      </div>
      <div className="mt-2 font-mono text-lg font-semibold tabular-nums text-rally-ink">
        {value}
      </div>
    </div>
  );
}

function InvoiceLinesTable({
  invoice,
  canRemove,
  removingLineId,
  onRemove,
}: {
  invoice: AdminInvoiceDetail | undefined;
  canRemove: boolean;
  removingLineId: string | null;
  onRemove: (lineId: string) => void;
}) {
  const lines = invoice?.lines ?? [];
  if (lines.length === 0) {
    return <p className="text-sm text-rally-muted">No invoice line items.</p>;
  }
  return (
    <div className="overflow-x-auto" data-testid="admin-student-invoice-lines">
      <table className="min-w-full text-left text-sm">
        <thead className="border-b border-neutral-200 text-xs uppercase tracking-overline text-rally-muted">
          <tr>
            <th className="py-2 pr-4 font-medium">Charge</th>
            <th className="py-2 pr-4 font-medium">Type</th>
            <th className="py-2 pr-4 font-medium">Qty</th>
            <th className="py-2 pr-4 font-medium">Unit</th>
            <th className="py-2 pr-4 font-medium">Amount</th>
            <th className="py-2 font-medium" />
          </tr>
        </thead>
        <tbody className="divide-y divide-neutral-100">
          {lines.map((line, index) => {
            const lineKey = line.line_id ?? `${line.description}-${index}`;
            const removable = canRemove && Boolean(line.line_id);
            return (
              <tr key={lineKey}>
                <td className="py-3 pr-4 align-top text-rally-ink">
                  {line.description}
                </td>
                <td className="py-3 pr-4 align-top text-rally-muted">
                  {line.line_type ?? "—"}
                </td>
                <td className="py-3 pr-4 align-top font-mono tabular-nums text-rally-ink">
                  {line.quantity ?? "—"}
                </td>
                <td className="py-3 pr-4 align-top font-mono tabular-nums text-rally-ink">
                  {line.unit_amount_cents == null
                    ? "—"
                    : formatCurrencyCents(line.unit_amount_cents)}
                </td>
                <td className="py-3 pr-4 align-top font-mono tabular-nums text-rally-ink">
                  {formatCurrencyCents(line.amount_cents)}
                </td>
                <td className="py-3 align-top">
                  <button
                    type="button"
                    className="inline-flex h-8 w-8 items-center justify-center rounded-md text-rally-muted hover:bg-red-50 hover:text-red-700 disabled:cursor-not-allowed disabled:opacity-40"
                    onClick={() => line.line_id && onRemove(line.line_id)}
                    disabled={!removable || removingLineId === line.line_id}
                    title={removable ? "Remove line" : "Line removal requires a draft invoice."}
                  >
                    {removingLineId === line.line_id ? (
                      <RefreshCw className="size-4 animate-spin" aria-hidden="true" />
                    ) : (
                      <Trash2 className="size-4" aria-hidden="true" />
                    )}
                    <span className="sr-only">Remove line</span>
                  </button>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function InvoiceSettlementPanel({ invoice }: { invoice: AdminInvoiceDetail | undefined }) {
  const allocations = invoice?.allocations ?? [];
  const credits = invoice?.credit_usage ?? [];
  if (allocations.length === 0 && credits.length === 0) {
    return null;
  }
  return (
    <div className="grid gap-4 md:grid-cols-2">
      <SettlementList
        label="Payment allocations"
        emptyLabel="No payment allocations"
        rows={allocations.map((item) => ({
          id: item.payment_id,
          amount: item.amount_cents,
        }))}
      />
      <SettlementList
        label="Credit usage"
        emptyLabel="No credit usage"
        rows={credits.map((item) => ({
          id: item.credit_id,
          amount: item.amount_cents,
        }))}
      />
    </div>
  );
}

function SettlementList({
  label,
  emptyLabel,
  rows,
}: {
  label: string;
  emptyLabel: string;
  rows: Array<{ id: string; amount: number }>;
}) {
  return (
    <div className="rounded-lg border border-neutral-200 bg-neutral-50 p-3">
      <div className="font-mono text-[10px] font-bold uppercase tracking-overline text-rally-muted">
        {label}
      </div>
      {rows.length === 0 ? (
        <p className="mt-2 text-xs text-rally-muted">{emptyLabel}</p>
      ) : (
        <dl className="mt-2 space-y-2 text-sm">
          {rows.map((row) => (
            <div key={row.id} className="flex items-center justify-between gap-3">
              <dt className="truncate text-rally-muted">{row.id}</dt>
              <dd className="font-mono tabular-nums text-rally-ink">
                {formatCurrencyCents(row.amount)}
              </dd>
            </div>
          ))}
        </dl>
      )}
    </div>
  );
}

const DISCOUNT_CATEGORIES: { value: TuitionDiscountCategory; label: string }[] = [
  { value: "owner_child", label: "Owner child" },
  { value: "coach_child", label: "Coach child" },
  { value: "scholarship", label: "Scholarship" },
  { value: "sibling", label: "Sibling" },
  { value: "other", label: "Other" },
];

const DISCOUNT_KINDS: { value: TuitionDiscountKind; label: string }[] = [
  { value: "waiver", label: "Waive fully" },
  { value: "percent", label: "% off" },
  { value: "amount_off", label: "$ off" },
  { value: "fixed_net", label: "Set final price" },
];

function previewNetCents(
  grossCents: number,
  kind: TuitionDiscountKind,
  value: string,
): number {
  const v = Number(value) || 0;
  switch (kind) {
    case "waiver":
      return 0;
    case "percent":
      return Math.max(grossCents - Math.round((grossCents * v) / 100), 0);
    case "amount_off":
      return Math.max(grossCents - Math.round(v * 100), 0);
    case "fixed_net":
      return Math.max(Math.round(v * 100), 0);
    default:
      return grossCents;
  }
}

function SessionsPanel({
  sessions,
  studentId,
  queryClient,
}: {
  sessions: AdminStudentSessionSummary[];
  studentId: string;
  queryClient: ReturnType<typeof useQueryClient>;
}) {
  const [moving, setMoving] = useState<AdminStudentSessionSummary | null>(null);
  const [billingOverride, setBillingOverride] =
    useState<AdminStudentSessionSummary | null>(null);
  const [overrideAmount, setOverrideAmount] = useState("");
  const [targetSessionId, setTargetSessionId] = useState("");
  const [effectiveDate, setEffectiveDate] = useState(() =>
    new Date().toISOString().slice(0, 10),
  );
  const [reason, setReason] = useState("");

  // Recurring tuition discount editor (#244)
  const [discounting, setDiscounting] =
    useState<AdminStudentSessionSummary | null>(null);
  const [discountCategory, setDiscountCategory] =
    useState<TuitionDiscountCategory>("scholarship");
  const [discountLabel, setDiscountLabel] = useState("");
  const [discountKind, setDiscountKind] =
    useState<TuitionDiscountKind>("waiver");
  const [discountValue, setDiscountValue] = useState("");
  const [discountStart, setDiscountStart] = useState(() =>
    new Date().toISOString().slice(0, 10),
  );
  const [discountNote, setDiscountNote] = useState("");

  const discountGross =
    discounting?.discount?.gross_cents ?? discounting?.amount_cents ?? 0;
  const discountPreviewNet = previewNetCents(
    discountGross,
    discountKind,
    discountValue,
  );

  const setDiscountMutation = useMutation({
    mutationFn: () =>
      setTuitionDiscount(discounting!.enrollment_id, {
        student_id: studentId,
        category: discountCategory,
        category_label: discountCategory === "other" ? discountLabel : null,
        kind: discountKind,
        percent_bps:
          discountKind === "percent"
            ? Math.round(Number(discountValue) * 100)
            : null,
        amount_off_cents:
          discountKind === "amount_off"
            ? Math.round(Number(discountValue) * 100)
            : null,
        fixed_net_cents:
          discountKind === "fixed_net"
            ? Math.round(Number(discountValue) * 100)
            : null,
        effective_start: discountStart,
        note: discountNote || null,
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: queryKeys.admin.studentDetail(studentId),
      });
      setDiscounting(null);
    },
  });

  const removeDiscountMutation = useMutation({
    mutationFn: () => removeTuitionDiscount(discounting!.enrollment_id),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: queryKeys.admin.studentDetail(studentId),
      });
      setDiscounting(null);
    },
  });

  const sessionsQuery = useQuery({
    queryKey: queryKeys.admin.sessions("upcoming"),
    queryFn: () => listAdminSessions(undefined, { window: "upcoming" }),
    enabled: Boolean(moving),
  });

  const transferMutation = useMutation({
    mutationFn: () =>
      transferEnrollment(moving!.enrollment_id, {
        target_session_id: targetSessionId,
        effective_date: effectiveDate,
        reason: reason || null,
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: queryKeys.admin.studentDetail(studentId),
      });
      setMoving(null);
      setTargetSessionId("");
      setReason("");
    },
  });

  const overrideMutation = useMutation({
    mutationFn: (amountCents: number | null) =>
      overrideEnrollmentFee(billingOverride!.enrollment_id, {
        amount_cents: amountCents,
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: queryKeys.admin.studentDetail(studentId),
      });
      setBillingOverride(null);
      setOverrideAmount("");
    },
  });

  const availableSessions: AdminSessionView[] = (
    sessionsQuery.data?.sessions ?? []
  ).filter((s) => s.session_id !== moving?.session_id);

  useEffect(() => {
    if (!moving && !billingOverride) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !transferMutation.isPending) {
        setMoving(null);
      }
      if (event.key === "Escape" && !overrideMutation.isPending) {
        setBillingOverride(null);
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [
    billingOverride,
    moving,
    overrideMutation.isPending,
    transferMutation.isPending,
  ]);

  const overridePriceCents = dollarsToCents(overrideAmount);
  const overrideAmountInvalid =
    Boolean(billingOverride) &&
    (overrideAmount.trim() === "" || overridePriceCents < 0);

  return (
    <>
      <Card p={20} className="lg:col-span-2">
        <div className="flex items-center justify-between gap-3">
          <Overline>Enrolled sessions</Overline>
          <span className="font-mono text-xs text-rally-muted tabular-nums">
            {sessions.length} active
          </span>
        </div>
        {sessions.length === 0 ? (
          <p
            className="mt-3 text-sm text-rally-muted"
            data-testid="admin-student-no-sessions"
          >
            No active session enrollments.
          </p>
        ) : (
          <div
            className="mt-3 overflow-x-auto"
            data-testid="admin-student-enrolled-sessions"
          >
            <table className="min-w-full text-left text-sm">
              <thead className="border-b border-neutral-200 text-xs uppercase tracking-overline text-rally-muted">
                <tr>
                  <th className="py-2 pr-4 font-medium">Session</th>
                  <th className="py-2 pr-4 font-medium">Schedule</th>
                  <th className="py-2 pr-4 font-medium">Billing</th>
                  <th className="py-2 pr-4 font-medium">Status</th>
                  <th className="py-2 font-medium" />
                </tr>
              </thead>
              <tbody className="divide-y divide-neutral-100">
                {sessions.map((session) => (
                  <tr key={session.enrollment_id}>
                    <td className="py-3 pr-4 align-top">
                      <div className="font-medium text-rally-ink">
                        {session.session_title}
                      </div>
                      <div className="text-xs text-rally-muted">
                        {session.location ?? session.session_id}
                      </div>
                    </td>
                    <td className="py-3 pr-4 align-top text-rally-muted">
                      {formatDateTimeRange(session.start_at, session.end_at)}
                    </td>
                    <td className="py-3 pr-4 align-top">
                      {session.discount ? (
                        <>
                          <div className="flex items-center gap-2">
                            <span className="font-mono tabular-nums text-rally-ink">
                              {formatCurrencyCents(session.discount.net_cents)}
                            </span>
                            {session.discount.discount_cents > 0 && (
                              <span className="font-mono text-xs tabular-nums text-rally-muted line-through">
                                {formatCurrencyCents(session.discount.gross_cents)}
                              </span>
                            )}
                          </div>
                          <span className="mt-1 inline-flex items-center rounded-full bg-emerald-50 px-2 py-0.5 text-xs font-medium text-emerald-700">
                            {session.discount.label}
                          </span>
                        </>
                      ) : (
                        <>
                          <div className="font-mono tabular-nums text-rally-ink">
                            {session.amount_cents == null
                              ? "—"
                              : formatCurrencyCents(session.amount_cents)}
                          </div>
                          <div className="text-xs text-rally-muted">
                            {session.payment_mode ??
                              session.subscription_status ??
                              "—"}
                          </div>
                        </>
                      )}
                    </td>
                    <td className="py-3 pr-4 align-top">
                      <StatusChip
                        status={session.subscription_status ?? session.status}
                      />
                    </td>
                    <td className="py-3 align-top">
                      <div className="flex items-center justify-end gap-3">
                        <button
                          className="text-xs font-medium text-rally-blue hover:underline"
                          onClick={() => {
                            setBillingOverride(session);
                            setOverrideAmount(
                              session.amount_cents == null
                                ? ""
                                : centsToDollarInput(session.amount_cents),
                            );
                          }}
                        >
                          Fee
                        </button>
                        <button
                          className="text-xs font-medium text-rally-blue hover:underline"
                          onClick={() => {
                            setMoving(session);
                            setTargetSessionId("");
                            setReason("");
                            setEffectiveDate(
                              new Date().toISOString().slice(0, 10),
                            );
                          }}
                        >
                          Move
                        </button>
                        <button
                          className="text-xs font-medium text-rally-blue hover:underline"
                          onClick={() => {
                            setDiscounting(session);
                            const d = session.discount;
                            setDiscountCategory(d?.category ?? "scholarship");
                            setDiscountLabel(d?.category_label ?? "");
                            setDiscountKind(d?.kind ?? "waiver");
                            setDiscountValue("");
                            setDiscountStart(
                              d?.effective_start ??
                                new Date().toISOString().slice(0, 10),
                            );
                            setDiscountNote("");
                          }}
                        >
                          {session.discount ? "Edit discount" : "Discount"}
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      {moving && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="move-session-title"
            className="w-full max-w-md rounded-xl bg-white p-6 shadow-xl dark:bg-neutral-900"
          >
            <h2
              id="move-session-title"
              className="mb-1 text-base font-semibold text-rally-ink"
            >
              Move student session
            </h2>
            <p className="mb-4 text-sm text-rally-muted">
              Moving <span className="font-medium">{moving.session_title}</span>
            </p>

            {transferMutation.isError && (
              <p className="mb-3 rounded bg-red-50 px-3 py-2 text-xs text-red-600">
                {String(transferMutation.error)}
              </p>
            )}

            <div className="space-y-3">
              <div>
                <label className="mb-1 block text-xs font-medium uppercase tracking-overline text-rally-muted">
                  New session
                </label>
                <select
                  className="w-full rounded-lg border border-neutral-200 bg-white px-3 py-2 text-sm text-rally-ink focus:outline-none focus:ring-2 focus:ring-rally-blue dark:bg-neutral-800"
                  value={targetSessionId}
                  onChange={(e) => setTargetSessionId(e.target.value)}
                  disabled={sessionsQuery.isPending}
                >
                  <option value="">
                    {sessionsQuery.isPending ? "Loading…" : "Select a session"}
                  </option>
                  {availableSessions.map((s) => (
                    <option key={s.session_id} value={s.session_id}>
                      {s.title} {s.coach_name ? `— ${s.coach_name}` : ""}
                    </option>
                  ))}
                </select>
              </div>

              <div>
                <label className="mb-1 block text-xs font-medium uppercase tracking-overline text-rally-muted">
                  Effective date
                </label>
                <input
                  type="date"
                  className="w-full rounded-lg border border-neutral-200 bg-white px-3 py-2 text-sm text-rally-ink focus:outline-none focus:ring-2 focus:ring-rally-blue dark:bg-neutral-800"
                  value={effectiveDate}
                  onChange={(e) => setEffectiveDate(e.target.value)}
                />
              </div>

              <div>
                <label className="mb-1 block text-xs font-medium uppercase tracking-overline text-rally-muted">
                  Reason (optional)
                </label>
                <textarea
                  className="w-full rounded-lg border border-neutral-200 bg-white px-3 py-2 text-sm text-rally-ink focus:outline-none focus:ring-2 focus:ring-rally-blue dark:bg-neutral-800"
                  rows={2}
                  placeholder="e.g. schedule conflict"
                  value={reason}
                  onChange={(e) => setReason(e.target.value)}
                />
              </div>
            </div>

            <div className="mt-5 flex justify-end gap-2">
              <Button
                variant="ghost"
                size="sm"
                onClick={() => setMoving(null)}
                disabled={transferMutation.isPending}
              >
                Cancel
              </Button>
              <Button
                size="sm"
                onClick={() => transferMutation.mutate()}
                disabled={!targetSessionId || transferMutation.isPending}
              >
                {transferMutation.isPending ? "Moving…" : "Move student"}
              </Button>
            </div>
          </div>
        </div>
      )}

      {discounting && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="discount-title"
            className="w-full max-w-md rounded-xl bg-white p-6 shadow-xl dark:bg-neutral-900"
          >
            <h2
              id="discount-title"
              className="mb-1 text-base font-semibold text-rally-ink"
            >
              Tuition discount
            </h2>
            <p className="mb-4 text-sm text-rally-muted">
              {discounting.session_title}
            </p>

            {(setDiscountMutation.isError || removeDiscountMutation.isError) && (
              <p className="mb-3 rounded bg-red-50 px-3 py-2 text-xs text-red-600">
                {String(
                  setDiscountMutation.error ?? removeDiscountMutation.error,
                )}
              </p>
            )}

            <div className="space-y-3">
              <div>
                <label className="mb-1 block text-xs font-medium uppercase tracking-overline text-rally-muted">
                  Category
                </label>
                <select
                  className="w-full rounded-lg border border-neutral-200 bg-white px-3 py-2 text-sm text-rally-ink focus:outline-none focus:ring-2 focus:ring-rally-blue dark:bg-neutral-800"
                  value={discountCategory}
                  onChange={(e) =>
                    setDiscountCategory(e.target.value as TuitionDiscountCategory)
                  }
                >
                  {DISCOUNT_CATEGORIES.map((c) => (
                    <option key={c.value} value={c.value}>
                      {c.label}
                    </option>
                  ))}
                </select>
              </div>

              {discountCategory === "other" && (
                <div>
                  <label className="mb-1 block text-xs font-medium uppercase tracking-overline text-rally-muted">
                    Custom label
                  </label>
                  <input
                    className="w-full rounded-lg border border-neutral-200 bg-white px-3 py-2 text-sm text-rally-ink focus:outline-none focus:ring-2 focus:ring-rally-blue dark:bg-neutral-800"
                    placeholder="e.g. Founding family rate"
                    value={discountLabel}
                    onChange={(e) => setDiscountLabel(e.target.value)}
                  />
                </div>
              )}

              <div>
                <label className="mb-1 block text-xs font-medium uppercase tracking-overline text-rally-muted">
                  Type
                </label>
                <select
                  className="w-full rounded-lg border border-neutral-200 bg-white px-3 py-2 text-sm text-rally-ink focus:outline-none focus:ring-2 focus:ring-rally-blue dark:bg-neutral-800"
                  value={discountKind}
                  onChange={(e) =>
                    setDiscountKind(e.target.value as TuitionDiscountKind)
                  }
                >
                  {DISCOUNT_KINDS.map((k) => (
                    <option key={k.value} value={k.value}>
                      {k.label}
                    </option>
                  ))}
                </select>
              </div>

              {discountKind !== "waiver" && (
                <div>
                  <label className="mb-1 block text-xs font-medium uppercase tracking-overline text-rally-muted">
                    {discountKind === "percent"
                      ? "Percent off"
                      : discountKind === "amount_off"
                        ? "Amount off ($)"
                        : "Final monthly price ($)"}
                  </label>
                  <input
                    type="number"
                    min="0"
                    className="w-full rounded-lg border border-neutral-200 bg-white px-3 py-2 text-sm text-rally-ink focus:outline-none focus:ring-2 focus:ring-rally-blue dark:bg-neutral-800"
                    value={discountValue}
                    onChange={(e) => setDiscountValue(e.target.value)}
                  />
                </div>
              )}

              <div>
                <label className="mb-1 block text-xs font-medium uppercase tracking-overline text-rally-muted">
                  Effective start
                </label>
                <input
                  type="date"
                  className="w-full rounded-lg border border-neutral-200 bg-white px-3 py-2 text-sm text-rally-ink focus:outline-none focus:ring-2 focus:ring-rally-blue dark:bg-neutral-800"
                  value={discountStart}
                  onChange={(e) => setDiscountStart(e.target.value)}
                />
              </div>

              <div>
                <label className="mb-1 block text-xs font-medium uppercase tracking-overline text-rally-muted">
                  Private note (optional)
                </label>
                <textarea
                  className="w-full rounded-lg border border-neutral-200 bg-white px-3 py-2 text-sm text-rally-ink focus:outline-none focus:ring-2 focus:ring-rally-blue dark:bg-neutral-800"
                  rows={2}
                  value={discountNote}
                  onChange={(e) => setDiscountNote(e.target.value)}
                />
              </div>

              <div className="rounded-lg bg-neutral-50 px-3 py-2 text-sm dark:bg-neutral-800">
                <span className="text-rally-muted">Gross </span>
                <span className="font-mono tabular-nums">
                  {formatCurrencyCents(discountGross)}
                </span>
                <span className="text-rally-muted"> → Net </span>
                <span className="font-mono font-semibold tabular-nums text-rally-ink">
                  {formatCurrencyCents(discountPreviewNet)}
                </span>
              </div>
            </div>

            <div className="mt-5 flex justify-between gap-2">
              <div>
                {discounting.discount && (
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => removeDiscountMutation.mutate()}
                    disabled={removeDiscountMutation.isPending}
                  >
                    {removeDiscountMutation.isPending ? "Removing…" : "Remove"}
                  </Button>
                )}
              </div>
              <div className="flex gap-2">
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => setDiscounting(null)}
                  disabled={setDiscountMutation.isPending}
                >
                  Cancel
                </Button>
                <Button
                  size="sm"
                  onClick={() => setDiscountMutation.mutate()}
                  disabled={
                    setDiscountMutation.isPending ||
                    (discountCategory === "other" && !discountLabel.trim()) ||
                    (discountKind !== "waiver" && !discountValue.trim())
                  }
                >
                  {setDiscountMutation.isPending ? "Saving…" : "Save discount"}
                </Button>
              </div>
            </div>
          </div>
        </div>
      )}

      {billingOverride && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="session-fee-title"
            className="w-full max-w-md rounded-xl bg-white p-6 shadow-xl dark:bg-neutral-900"
          >
            <h2
              id="session-fee-title"
              className="mb-1 text-base font-semibold text-rally-ink"
            >
              Update session fee
            </h2>
            <p className="mb-4 text-sm text-rally-muted">
              {billingOverride.session_title}
            </p>

            {overrideMutation.isError && (
              <p className="mb-3 rounded bg-red-50 px-3 py-2 text-xs text-red-600">
                {getErrorMessage(overrideMutation.error)}
              </p>
            )}

            <div className="space-y-3">
              <div className="rounded-lg border border-neutral-200 p-3">
                <div className="flex items-center justify-between text-sm">
                  <span className="text-rally-muted">Current fee</span>
                  <span className="font-mono text-rally-ink tabular-nums">
                    {billingOverride.amount_cents == null
                      ? "—"
                      : formatCurrencyCents(billingOverride.amount_cents)}
                  </span>
                </div>
              </div>

              <div>
                <label
                  className="mb-1 block text-xs font-medium uppercase tracking-overline text-rally-muted"
                  htmlFor="session-fee-amount"
                >
                  Monthly fee
                </label>
                <input
                  id="session-fee-amount"
                  type="number"
                  min="0"
                  step="0.01"
                  className="w-full rounded-lg border border-neutral-200 bg-white px-3 py-2 text-sm text-rally-ink focus:outline-none focus:ring-2 focus:ring-rally-blue dark:bg-neutral-800"
                  value={overrideAmount}
                  onChange={(event) => setOverrideAmount(event.target.value)}
                />
                <p className="mt-1 text-xs text-rally-muted">
                  Use 0.00 to waive this student&apos;s session fee.
                </p>
                {overrideAmountInvalid && (
                  <p className="mt-1 text-xs text-red-600">
                    Enter a valid amount.
                  </p>
                )}
              </div>
            </div>

            <div className="mt-5 flex flex-wrap justify-end gap-2">
              <Button
                variant="ghost"
                size="sm"
                onClick={() => setBillingOverride(null)}
                disabled={overrideMutation.isPending}
              >
                Cancel
              </Button>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => overrideMutation.mutate(null)}
                disabled={overrideMutation.isPending}
              >
                Use default fee
              </Button>
              <Button
                size="sm"
                onClick={() => overrideMutation.mutate(overridePriceCents)}
                disabled={overrideAmountInvalid || overrideMutation.isPending}
              >
                {overrideMutation.isPending ? "Saving…" : "Save fee"}
              </Button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}

function CreateInvoiceDialog({
  student,
  pending,
  error,
  onCancel,
  onSubmit,
}: {
  student: AdminStudentDetail;
  pending: boolean;
  error: string | null | undefined;
  onCancel: () => void;
  onSubmit: (payload: { period: string; due_date: string; enrollment_id?: string | null }) => void;
}) {
  const [period, setPeriod] = useState(() => new Date().toISOString().slice(0, 7));
  const [dueDate, setDueDate] = useState(() => new Date().toISOString().slice(0, 10));
  const [enrollmentId, setEnrollmentId] = useState("");
  const sessions = student.enrolled_sessions ?? [];

  return (
    <BillingDialogFrame title="Create draft invoice" onCancel={onCancel}>
      {error && <BillingDialogError message={error} />}
      <div className="space-y-3">
        <Field label="Period" htmlFor="billing-create-period">
          <input
            id="billing-create-period"
            type="month"
            value={period}
            onChange={(event) => setPeriod(event.target.value)}
            className="h-10 w-full rounded-md border border-neutral-200 bg-white px-3 text-sm text-rally-base outline-none focus:border-rally-cobalt-600 focus:ring-2 focus:ring-rally-cobalt-600/15"
          />
        </Field>
        <Field label="Due date" htmlFor="billing-create-due-date">
          <input
            id="billing-create-due-date"
            type="date"
            value={dueDate}
            onChange={(event) => setDueDate(event.target.value)}
            className="h-10 w-full rounded-md border border-neutral-200 bg-white px-3 text-sm text-rally-base outline-none focus:border-rally-cobalt-600 focus:ring-2 focus:ring-rally-cobalt-600/15"
          />
        </Field>
        <Field label="Enrollment" htmlFor="billing-create-enrollment">
          <select
            id="billing-create-enrollment"
            value={enrollmentId}
            onChange={(event) => setEnrollmentId(event.target.value)}
            className="h-10 w-full rounded-md border border-neutral-200 bg-white px-3 text-sm text-rally-base outline-none focus:border-rally-cobalt-600 focus:ring-2 focus:ring-rally-cobalt-600/15"
          >
            <option value="">No enrollment link</option>
            {sessions.map((session) => (
              <option key={session.enrollment_id} value={session.enrollment_id}>
                {session.session_title}
              </option>
            ))}
          </select>
        </Field>
      </div>
      <BillingDialogActions onCancel={onCancel}>
        <Button
          size="sm"
          disabled={!period || !dueDate || pending}
          icon={pending ? <RefreshCw className="size-3.5 animate-spin" aria-hidden="true" /> : undefined}
          onClick={() =>
            onSubmit({
              period,
              due_date: dueDate,
              enrollment_id: enrollmentId || null,
            })
          }
        >
          {pending ? "Creating..." : "Create invoice"}
        </Button>
      </BillingDialogActions>
    </BillingDialogFrame>
  );
}

function AddInvoiceLineDialog({
  invoiceId,
  products,
  productsLoading,
  onCancel,
  onSaved,
  onDone,
}: {
  invoiceId: string;
  products: AdminBillingProductView[];
  productsLoading: boolean;
  onCancel: () => void;
  onSaved: (payload: AddInvoiceLineRequest) => Promise<unknown>;
  onDone: () => void;
}) {
  const [productId, setProductId] = useState("");
  const [description, setDescription] = useState("");
  const [lineType, setLineType] = useState("fee");
  const [quantity, setQuantity] = useState("1");
  const [unitAmount, setUnitAmount] = useState("");

  useEffect(() => {
    const selected = products.find((product) => product.product_id === productId);
    if (!selected) return;
    setDescription(selected.name);
    setLineType(selected.line_type);
    setUnitAmount(centsToDollarInput(selected.default_unit_amount_cents));
  }, [productId, products]);

  const mutation = useMutation({
    mutationFn: () =>
      onSaved({
        product_id: productId || null,
        description: description.trim(),
        line_type: lineType.trim(),
        quantity: Number.parseInt(quantity, 10),
        unit_amount_cents: dollarsToCents(unitAmount),
      }),
    onSuccess: onDone,
  });
  const canSubmit =
    description.trim().length > 0 &&
    lineType.trim().length > 0 &&
    Number.parseInt(quantity, 10) > 0 &&
    dollarsToCents(unitAmount) >= 0;

  return (
    <BillingDialogFrame title="Add invoice charge" onCancel={onCancel}>
      {getErrorMessage(mutation.error) && (
        <BillingDialogError message={getErrorMessage(mutation.error)!} />
      )}
      <div className="space-y-3">
        <Field label="Product" htmlFor={`billing-product-${invoiceId}`}>
          <select
            id={`billing-product-${invoiceId}`}
            value={productId}
            onChange={(event) => setProductId(event.target.value)}
            className="h-10 w-full rounded-md border border-neutral-200 bg-white px-3 text-sm text-rally-base outline-none focus:border-rally-cobalt-600 focus:ring-2 focus:ring-rally-cobalt-600/15"
          >
            <option value="">{productsLoading ? "Loading products..." : "Custom charge"}</option>
            {products.map((product) => (
              <option key={product.product_id} value={product.product_id}>
                {product.name} - {formatCurrencyCents(product.default_unit_amount_cents)}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Description" htmlFor={`billing-line-description-${invoiceId}`}>
          <input
            id={`billing-line-description-${invoiceId}`}
            value={description}
            onChange={(event) => setDescription(event.target.value)}
            className="h-10 w-full rounded-md border border-neutral-200 bg-white px-3 text-sm text-rally-base outline-none focus:border-rally-cobalt-600 focus:ring-2 focus:ring-rally-cobalt-600/15"
          />
        </Field>
        <div className="grid gap-3 sm:grid-cols-3">
          <Field label="Type" htmlFor={`billing-line-type-${invoiceId}`}>
            <input
              id={`billing-line-type-${invoiceId}`}
              value={lineType}
              onChange={(event) => setLineType(event.target.value)}
              className="h-10 w-full rounded-md border border-neutral-200 bg-white px-3 text-sm text-rally-base outline-none focus:border-rally-cobalt-600 focus:ring-2 focus:ring-rally-cobalt-600/15"
            />
          </Field>
          <Field label="Qty" htmlFor={`billing-line-quantity-${invoiceId}`}>
            <input
              id={`billing-line-quantity-${invoiceId}`}
              type="number"
              min="1"
              step="1"
              value={quantity}
              onChange={(event) => setQuantity(event.target.value)}
              className="h-10 w-full rounded-md border border-neutral-200 bg-white px-3 text-sm text-rally-base outline-none focus:border-rally-cobalt-600 focus:ring-2 focus:ring-rally-cobalt-600/15"
            />
          </Field>
          <Field label="Unit amount" htmlFor={`billing-line-amount-${invoiceId}`}>
            <input
              id={`billing-line-amount-${invoiceId}`}
              inputMode="decimal"
              value={unitAmount}
              onChange={(event) => setUnitAmount(event.target.value)}
              className="h-10 w-full rounded-md border border-neutral-200 bg-white px-3 text-sm text-rally-base outline-none focus:border-rally-cobalt-600 focus:ring-2 focus:ring-rally-cobalt-600/15"
              placeholder="0.00"
            />
          </Field>
        </div>
      </div>
      <BillingDialogActions onCancel={onCancel}>
        <Button
          size="sm"
          disabled={!canSubmit || mutation.isPending}
          icon={mutation.isPending ? <RefreshCw className="size-3.5 animate-spin" aria-hidden="true" /> : undefined}
          onClick={() => mutation.mutate()}
        >
          {mutation.isPending ? "Adding..." : "Add charge"}
        </Button>
      </BillingDialogActions>
    </BillingDialogFrame>
  );
}

function RecordPaymentDialog({
  balanceDueCents,
  onCancel,
  onSaved,
  onDone,
}: {
  balanceDueCents: number;
  onCancel: () => void;
  onSaved: (payload: RecordManualPaymentRequest) => Promise<{ payment_id: string }>;
  onDone: (paymentId: string) => void;
}) {
  const [amount, setAmount] = useState(() => centsToDollarInput(balanceDueCents));
  const [method, setMethod] = useState("cash");
  const [referenceNumber, setReferenceNumber] = useState("");
  const [notes, setNotes] = useState("");
  const mutation = useMutation({
    mutationFn: () =>
      onSaved({
        amount_cents: dollarsToCents(amount),
        payment_method: method,
        reference_number: referenceNumber.trim() || null,
        notes: notes.trim(),
      }),
    onSuccess: (result) => onDone(result.payment_id),
  });
  const amountCents = dollarsToCents(amount);

  return (
    <BillingDialogFrame title="Record manual payment" onCancel={onCancel}>
      {getErrorMessage(mutation.error) && (
        <BillingDialogError message={getErrorMessage(mutation.error)!} />
      )}
      <div className="space-y-3">
        <Field label="Amount" htmlFor="billing-payment-amount">
          <input
            id="billing-payment-amount"
            inputMode="decimal"
            value={amount}
            onChange={(event) => setAmount(event.target.value)}
            className="h-10 w-full rounded-md border border-neutral-200 bg-white px-3 text-sm text-rally-base outline-none focus:border-rally-cobalt-600 focus:ring-2 focus:ring-rally-cobalt-600/15"
          />
        </Field>
        <Field label="Method" htmlFor="billing-payment-method">
          <select
            id="billing-payment-method"
            value={method}
            onChange={(event) => setMethod(event.target.value)}
            className="h-10 w-full rounded-md border border-neutral-200 bg-white px-3 text-sm text-rally-base outline-none focus:border-rally-cobalt-600 focus:ring-2 focus:ring-rally-cobalt-600/15"
          >
            <option value="cash">Cash</option>
            <option value="check">Check</option>
            <option value="zelle">Zelle</option>
            <option value="venmo">Venmo</option>
            <option value="bank_transfer">Bank transfer</option>
            <option value="other">Other</option>
          </select>
        </Field>
        <Field label="Reference" htmlFor="billing-payment-reference">
          <input
            id="billing-payment-reference"
            value={referenceNumber}
            onChange={(event) => setReferenceNumber(event.target.value)}
            className="h-10 w-full rounded-md border border-neutral-200 bg-white px-3 text-sm text-rally-base outline-none focus:border-rally-cobalt-600 focus:ring-2 focus:ring-rally-cobalt-600/15"
          />
        </Field>
        <Field label="Notes" htmlFor="billing-payment-notes">
          <textarea
            id="billing-payment-notes"
            rows={3}
            value={notes}
            onChange={(event) => setNotes(event.target.value)}
            className="w-full rounded-md border border-neutral-200 bg-white px-3 py-2 text-sm text-rally-base outline-none focus:border-rally-cobalt-600 focus:ring-2 focus:ring-rally-cobalt-600/15"
          />
        </Field>
      </div>
      <BillingDialogActions onCancel={onCancel}>
        <Button
          size="sm"
          disabled={amountCents <= 0 || mutation.isPending}
          icon={mutation.isPending ? <RefreshCw className="size-3.5 animate-spin" aria-hidden="true" /> : undefined}
          onClick={() => mutation.mutate()}
        >
          {mutation.isPending ? "Recording..." : "Record payment"}
        </Button>
      </BillingDialogActions>
    </BillingDialogFrame>
  );
}

function VoidInvoiceDialog({
  onCancel,
  onSaved,
  onDone,
}: {
  onCancel: () => void;
  onSaved: (reason: string) => Promise<unknown>;
  onDone: () => void;
}) {
  const [reason, setReason] = useState("");
  const mutation = useMutation({
    mutationFn: () => onSaved(reason.trim()),
    onSuccess: onDone,
  });

  return (
    <BillingDialogFrame title="Void invoice" onCancel={onCancel}>
      {getErrorMessage(mutation.error) && (
        <BillingDialogError message={getErrorMessage(mutation.error)!} />
      )}
      <Field label="Reason" htmlFor="billing-void-reason">
        <textarea
          id="billing-void-reason"
          rows={3}
          value={reason}
          onChange={(event) => setReason(event.target.value)}
          className="w-full rounded-md border border-neutral-200 bg-white px-3 py-2 text-sm text-rally-base outline-none focus:border-rally-cobalt-600 focus:ring-2 focus:ring-rally-cobalt-600/15"
          required
        />
      </Field>
      <BillingDialogActions onCancel={onCancel}>
        <Button
          size="sm"
          variant="danger"
          disabled={reason.trim().length === 0 || mutation.isPending}
          icon={mutation.isPending ? <RefreshCw className="size-3.5 animate-spin" aria-hidden="true" /> : undefined}
          onClick={() => mutation.mutate()}
        >
          {mutation.isPending ? "Voiding..." : "Void invoice"}
        </Button>
      </BillingDialogActions>
    </BillingDialogFrame>
  );
}

function BillingDialogFrame({
  title,
  children,
  onCancel,
}: {
  title: string;
  children: ReactNode;
  onCancel: () => void;
}) {
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onCancel();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onCancel]);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="billing-dialog-title"
        className="w-full max-w-lg rounded-xl bg-white p-6 shadow-xl dark:bg-neutral-900"
      >
        <h2 id="billing-dialog-title" className="mb-4 text-base font-semibold text-rally-ink">
          {title}
        </h2>
        {children}
      </div>
    </div>
  );
}

function BillingDialogActions({
  children,
  onCancel,
}: {
  children: ReactNode;
  onCancel: () => void;
}) {
  return (
    <div className="mt-5 flex justify-end gap-2">
      <Button variant="ghost" size="sm" onClick={onCancel}>
        Cancel
      </Button>
      {children}
    </div>
  );
}

function BillingDialogError({ message }: { message: string }) {
  return <p className="mb-3 rounded-md bg-red-50 px-3 py-2 text-xs text-red-700">{message}</p>;
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

function Header({ student }: { student: AdminStudentDetail }) {
  return (
    <Card p={20}>
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-center gap-4 min-w-0">
          <Avatar name={student.full_name} size={56} />
          <div className="min-w-0">
            <h2 className="font-display text-xl font-semibold tracking-[-0.01em] text-rally-ink truncate">
              {student.full_name}
            </h2>
            <div className="mt-1 flex items-center gap-2">
              <StatusChip status={student.status} />
            </div>
          </div>
        </div>
        <div className="text-sm text-rally-muted">
          <div className="font-medium text-rally-ink">
            {student.parent_name ?? student.parent_email ?? "Parent on file"}
          </div>
          {student.parent_email && (
            <a
              href={`mailto:${student.parent_email}`}
              className="block hover:underline focus:outline-none focus:ring-2 focus:ring-rally-cobalt-600 rounded"
            >
              {student.parent_email}
            </a>
          )}
          {student.parent_phone && (
            <a
              href={`tel:${student.parent_phone}`}
              className="block hover:underline focus:outline-none focus:ring-2 focus:ring-rally-cobalt-600 rounded"
            >
              {student.parent_phone}
            </a>
          )}
        </div>
      </div>
    </Card>
  );
}

function StatusChip({ status }: { status: string }) {
  const normalized = status.toLowerCase();
  const variant =
    normalized === "active" || normalized === "succeeded"
      ? "enrolled"
      : normalized === "paid"
        ? "paid"
        : normalized === "paused"
          ? "paused"
          : normalized === "pending" ||
              normalized === "unpaid" ||
              normalized === "open"
            ? "pending"
            : normalized === "failed"
              ? "failed"
              : normalized === "partially_paid" || normalized === "partial"
                ? "partial"
                : "expired";
  return <Chip variant={variant} label={status.toUpperCase()} />;
}

function formatCurrencyCents(cents: number) {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  }).format(cents / 100);
}

function centsToDollarInput(cents: number) {
  return (cents / 100).toFixed(2);
}

function dollarsToCents(value: string) {
  const normalized = value.replace(/[$,]/g, "").trim();
  if (!normalized) return 0;
  const amount = Number.parseFloat(normalized);
  if (!Number.isFinite(amount)) return -1;
  return Math.round(amount * 100);
}

function getErrorMessage(error: unknown) {
  if (!error) return null;
  const message = error instanceof Error ? error.message : "Request failed.";
  if (message.includes("no_saved_payment_method")) {
    return "This parent has no saved card on file. Use Send to email a payment link, or Record payment to log a manual payment.";
  }
  return message;
}

function formatDate(value: string | null | undefined) {
  if (!value) return "—";
  return new Date(value).toLocaleDateString();
}

function formatDateTime(value: string | null | undefined) {
  if (!value) return "—";
  return new Date(value).toLocaleString([], {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

function formatDateTimeRange(
  startAt: string | null | undefined,
  endAt: string | null | undefined,
) {
  if (!startAt && !endAt) return "—";
  if (!endAt) return formatDateTime(startAt);
  if (!startAt) return formatDateTime(endAt);
  return `${formatDateTime(startAt)} - ${formatDateTime(endAt)}`;
}

function DetailList({
  rows,
}: {
  rows: Array<{ label: string; value: string }>;
}) {
  return (
    <dl className="mt-3 grid grid-cols-1 gap-3 text-sm">
      {rows.map((row) => (
        <div key={row.label} className="flex items-center justify-between">
          <dt className="text-rally-muted">{row.label}</dt>
          <dd className="font-mono text-rally-ink tabular-nums">{row.value}</dd>
        </div>
      ))}
    </dl>
  );
}

function StudentEditForm({
  mode,
  student,
  onSaved,
}: {
  mode: StudentEditMode;
  student: AdminStudentDetail;
  onSaved: () => void;
}) {
  const [fullName, setFullName] = useState(student.full_name);
  const [dateOfBirth, setDateOfBirth] = useState(student.date_of_birth ?? "");
  const [status, setStatus] = useState<EditableStatus>(
    (student.status as EditableStatus) ?? "active",
  );
  const [notes, setNotes] = useState(student.notes ?? "");
  const [previousExperience, setPreviousExperience] = useState(
    student.previous_experience ?? "",
  );
  const [medicalNotes, setMedicalNotes] = useState(
    student.medical_notes ?? "",
  );
  const [emergencyContactName, setEmergencyContactName] = useState(
    student.emergency_contact_name ?? "",
  );
  const [emergencyContactPhone, setEmergencyContactPhone] = useState(
    student.emergency_contact_phone ?? "",
  );
  const [tShirtSize, setTShirtSize] = useState(student.t_shirt_size ?? "");
  const [reason, setReason] = useState("Admin profile update");
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [submitOk, setSubmitOk] = useState(false);

  // Keep local state in sync if the server-side data refreshes.
  useEffect(() => {
    setFullName(student.full_name);
    setDateOfBirth(student.date_of_birth ?? "");
    setStatus((student.status as EditableStatus) ?? "active");
    setNotes(student.notes ?? "");
    setPreviousExperience(student.previous_experience ?? "");
    setMedicalNotes(student.medical_notes ?? "");
    setEmergencyContactName(student.emergency_contact_name ?? "");
    setEmergencyContactPhone(student.emergency_contact_phone ?? "");
    setTShirtSize(student.t_shirt_size ?? "");
  }, [
    student.full_name,
    student.date_of_birth,
    student.status,
    student.notes,
    student.previous_experience,
    student.medical_notes,
    student.emergency_contact_name,
    student.emergency_contact_phone,
    student.t_shirt_size,
  ]);

  const mutation = useMutation({
    mutationFn: (payload: UpdateAdminStudentRequest) =>
      updateAdminStudent(student.student_id, payload),
    onSuccess: () => {
      setSubmitError(null);
      setSubmitOk(true);
      onSaved();
    },
    onError: (err: unknown) => {
      setSubmitOk(false);
      const message =
        err instanceof Error ? err.message : "Could not save changes.";
      setSubmitError(message);
    },
  });

  const dirtyFields = {
    fullName: fullName !== student.full_name,
    dateOfBirth: dateOfBirth !== (student.date_of_birth ?? ""),
    status: status !== student.status,
    notes: (notes ?? "") !== (student.notes ?? ""),
    previousExperience:
      previousExperience !== (student.previous_experience ?? ""),
    medicalNotes: medicalNotes !== (student.medical_notes ?? ""),
    emergencyContactName:
      emergencyContactName !== (student.emergency_contact_name ?? ""),
    emergencyContactPhone:
      emergencyContactPhone !== (student.emergency_contact_phone ?? ""),
    tShirtSize: tShirtSize !== (student.t_shirt_size ?? ""),
  };

  const dirty =
    mode === "overview"
      ? dirtyFields.fullName ||
        dirtyFields.dateOfBirth ||
        dirtyFields.status ||
        dirtyFields.notes
      : mode === "training"
        ? dirtyFields.previousExperience ||
          dirtyFields.medicalNotes ||
          dirtyFields.emergencyContactName ||
          dirtyFields.emergencyContactPhone
        : dirtyFields.tShirtSize;

  const reset = () => {
    setFullName(student.full_name);
    setDateOfBirth(student.date_of_birth ?? "");
    setStatus((student.status as EditableStatus) ?? "active");
    setNotes(student.notes ?? "");
    setPreviousExperience(student.previous_experience ?? "");
    setMedicalNotes(student.medical_notes ?? "");
    setEmergencyContactName(student.emergency_contact_name ?? "");
    setEmergencyContactPhone(student.emergency_contact_phone ?? "");
    setTShirtSize(student.t_shirt_size ?? "");
    setSubmitError(null);
    setSubmitOk(false);
  };

  return (
    <form
      className="mt-3 space-y-4"
      data-testid={`admin-student-${mode}-edit-form`}
      onSubmit={(e) => {
        e.preventDefault();
        setSubmitOk(false);
        setSubmitError(null);
        const payload: UpdateAdminStudentRequest = {};
        if (mode === "overview") {
          if (dirtyFields.fullName) payload.full_name = fullName;
          if (dirtyFields.dateOfBirth)
            payload.date_of_birth = dateOfBirth || null;
          if (dirtyFields.status) payload.status = status;
          if (dirtyFields.notes) payload.notes = notes || null;
        }
        if (mode === "training") {
          if (dirtyFields.previousExperience)
            payload.previous_experience = previousExperience;
          if (dirtyFields.medicalNotes)
            payload.medical_notes = medicalNotes;
          if (dirtyFields.emergencyContactName)
            payload.emergency_contact_name = emergencyContactName;
          if (dirtyFields.emergencyContactPhone)
            payload.emergency_contact_phone = emergencyContactPhone;
        }
        if (mode === "family" && dirtyFields.tShirtSize) {
          payload.t_shirt_size = tShirtSize;
        }
        payload.reason = reason;
        mutation.mutate(payload);
      }}
    >
      {mode === "overview" && (
        <>
          <Field label="Full name" htmlFor="student-full-name">
            <input
              id="student-full-name"
              value={fullName}
              onChange={(e) => setFullName(e.target.value)}
              className="h-10 w-full rounded-md border border-neutral-200 bg-white px-3 text-sm text-rally-base outline-none focus:border-rally-cobalt-600 focus:ring-2 focus:ring-rally-cobalt-600/15"
              required
              minLength={1}
              maxLength={120}
            />
          </Field>

          <Field label="Date of birth" htmlFor="student-dob">
            <input
              id="student-dob"
              type="date"
              value={dateOfBirth}
              onChange={(e) => setDateOfBirth(e.target.value)}
              className="h-10 w-full rounded-md border border-neutral-200 bg-white px-3 text-sm text-rally-base outline-none focus:border-rally-cobalt-600 focus:ring-2 focus:ring-rally-cobalt-600/15"
            />
          </Field>

          <Field label="Status" htmlFor="student-status">
            <select
              id="student-status"
              value={status}
              onChange={(e) => setStatus(e.target.value as EditableStatus)}
              className="h-10 w-full rounded-md border border-neutral-200 bg-white px-3 text-sm text-rally-base outline-none focus:border-rally-cobalt-600 focus:ring-2 focus:ring-rally-cobalt-600/15"
            >
              <option value="active">Active</option>
              <option value="paused">Paused</option>
              <option value="inactive">Inactive</option>
              <option value="cancelled">Cancelled</option>
            </select>
          </Field>

          <Field label="Internal notes" htmlFor="student-notes">
            <textarea
              id="student-notes"
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              rows={4}
              maxLength={2000}
              className="w-full rounded-md border border-neutral-200 bg-white px-3 py-2 text-sm text-rally-base outline-none focus:border-rally-cobalt-600 focus:ring-2 focus:ring-rally-cobalt-600/15"
              placeholder="Allergies, behavioural notes, comms preferences..."
            />
          </Field>
        </>
      )}

      {mode === "training" && (
        <>
          <Field label="Previous experience" htmlFor="student-previous-experience">
            <textarea
              id="student-previous-experience"
              value={previousExperience}
              onChange={(e) => setPreviousExperience(e.target.value)}
              rows={3}
              maxLength={1000}
              className="w-full rounded-md border border-neutral-200 bg-white px-3 py-2 text-sm text-rally-base outline-none focus:border-rally-cobalt-600 focus:ring-2 focus:ring-rally-cobalt-600/15"
              placeholder="Prior coaching, club play, school teams"
            />
          </Field>

          <Field label="Medical notes" htmlFor="student-medical-notes">
            <textarea
              id="student-medical-notes"
              value={medicalNotes}
              onChange={(e) => setMedicalNotes(e.target.value)}
              rows={3}
              maxLength={1000}
              className="w-full rounded-md border border-neutral-200 bg-white px-3 py-2 text-sm text-rally-base outline-none focus:border-rally-cobalt-600 focus:ring-2 focus:ring-rally-cobalt-600/15"
              placeholder="Allergies, injuries, health notes"
            />
          </Field>

          <div className="grid gap-4 sm:grid-cols-2">
            <Field
              label="Emergency contact name"
              htmlFor="student-emergency-contact-name"
            >
              <input
                id="student-emergency-contact-name"
                value={emergencyContactName}
                onChange={(e) => setEmergencyContactName(e.target.value)}
                className="h-10 w-full rounded-md border border-neutral-200 bg-white px-3 text-sm text-rally-base outline-none focus:border-rally-cobalt-600 focus:ring-2 focus:ring-rally-cobalt-600/15"
                maxLength={120}
              />
            </Field>

            <Field
              label="Emergency contact phone"
              htmlFor="student-emergency-contact-phone"
            >
              <input
                id="student-emergency-contact-phone"
                value={emergencyContactPhone}
                onChange={(e) => setEmergencyContactPhone(e.target.value)}
                className="h-10 w-full rounded-md border border-neutral-200 bg-white px-3 text-sm text-rally-base outline-none focus:border-rally-cobalt-600 focus:ring-2 focus:ring-rally-cobalt-600/15"
                maxLength={40}
              />
            </Field>
          </div>
        </>
      )}

      {mode === "family" && (
        <Field label="T-shirt size" htmlFor="student-t-shirt-size">
          <input
            id="student-t-shirt-size"
            value={tShirtSize}
            onChange={(e) => setTShirtSize(e.target.value)}
            className="h-10 w-full rounded-md border border-neutral-200 bg-white px-3 text-sm text-rally-base outline-none focus:border-rally-cobalt-600 focus:ring-2 focus:ring-rally-cobalt-600/15"
            maxLength={20}
          />
        </Field>
      )}

      <Field label="Reason" htmlFor="student-edit-reason">
        <input
          id="student-edit-reason"
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          className="h-10 w-full rounded-md border border-neutral-200 bg-white px-3 text-sm text-rally-base outline-none focus:border-rally-cobalt-600 focus:ring-2 focus:ring-rally-cobalt-600/15"
          required
          maxLength={500}
        />
      </Field>

      {submitError && (
        <p
          role="alert"
          data-testid="admin-student-edit-error"
          className="rounded-md border border-red-200 bg-red-50 p-2 text-sm text-red-700"
        >
          {submitError}
        </p>
      )}
      {submitOk && (
        <p
          role="status"
          data-testid="admin-student-edit-ok"
          className="rounded-md border border-emerald-200 bg-emerald-50 p-2 text-sm text-emerald-800"
        >
          Saved.
        </p>
      )}

      <div className="flex items-center gap-2">
        <Button
          type="submit"
          variant="primary"
          size="sm"
          disabled={!dirty || mutation.isPending}
          icon={
            mutation.isPending ? (
              <RefreshCw className="size-3.5 animate-spin" />
            ) : undefined
          }
        >
          {mutation.isPending ? "Saving…" : "Save changes"}
        </Button>
        {dirty && (
          <Button
            type="button"
            variant="secondary"
            size="sm"
            onClick={reset}
          >
            Reset
          </Button>
        )}
      </div>
    </form>
  );
}

function ChangeParentPanel({
  student,
  parents,
  parentsLoading,
  parentsError,
  onSaved,
}: {
  student: AdminStudentDetail;
  parents: AdminUserView[];
  parentsLoading: boolean;
  parentsError: boolean;
  onSaved: () => void;
}) {
  const activeParents = useMemo(
    () => parents.filter((parent) => parent.status === "active"),
    [parents],
  );
  const [search, setSearch] = useState("");
  const [parentId, setParentId] = useState("");
  const [reason, setReason] = useState("Admin parent account correction");
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [submitOk, setSubmitOk] = useState(false);
  const [warnings, setWarnings] = useState<string[]>([]);

  const filteredParents = useMemo(() => {
    const normalized = search.trim().toLowerCase();
    if (!normalized) return activeParents;
    return activeParents.filter((parent) => {
      const haystack =
        `${parent.display_name} ${parent.email} ${parent.phone ?? ""}`.toLowerCase();
      return haystack.includes(normalized);
    });
  }, [activeParents, search]);

  useEffect(() => {
    if (
      !parentId ||
      filteredParents.some((parent) => parent.user_id === parentId)
    )
      return;
    setParentId("");
  }, [filteredParents, parentId]);

  useEffect(() => {
    setParentId("");
    setSubmitError(null);
    setSubmitOk(false);
    setWarnings([]);
  }, [student.student_id, student.parent_id]);

  const selectedParent = activeParents.find(
    (parent) => parent.user_id === parentId,
  );
  const canSubmit = Boolean(
    parentId && parentId !== student.parent_id && reason.trim(),
  );

  const mutation = useMutation({
    mutationFn: (payload: ChangeAdminStudentParentRequest) =>
      changeAdminStudentParent(student.student_id, payload),
    onSuccess: (result) => {
      setSubmitError(null);
      setSubmitOk(true);
      setWarnings(result.warnings);
      setParentId("");
      setSearch("");
      onSaved();
    },
    onError: (err: unknown) => {
      setSubmitOk(false);
      setWarnings([]);
      setSubmitError(
        err instanceof Error ? err.message : "Could not change parent account.",
      );
    },
  });

  return (
    <form
      className="mt-3 space-y-4"
      data-testid="admin-student-change-parent-form"
      onSubmit={(event) => {
        event.preventDefault();
        if (!canSubmit) return;
        setSubmitError(null);
        setSubmitOk(false);
        setWarnings([]);
        mutation.mutate({ parent_id: parentId, reason: reason.trim() });
      }}
    >
      <DetailList
        rows={[
          {
            label: "Current parent",
            value:
              student.parent_name ?? student.parent_email ?? "Parent on file",
          },
          {
            label: "Available parents",
            value: parentsLoading ? "Loading" : String(activeParents.length),
          },
        ]}
      />

      {parentsError && (
        <p
          role="alert"
          className="rounded-md border border-red-200 bg-red-50 p-2 text-sm text-red-700"
        >
          Could not load parent accounts.
        </p>
      )}

      <Field label="Search parents" htmlFor="student-parent-search">
        <input
          id="student-parent-search"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          className="h-10 w-full rounded-md border border-neutral-200 bg-white px-3 text-sm text-rally-base outline-none focus:border-rally-cobalt-600 focus:ring-2 focus:ring-rally-cobalt-600/15"
          placeholder="Name, email, or phone"
          disabled={parentsLoading || parentsError}
        />
      </Field>

      <Field label="New parent" htmlFor="student-parent-id">
        <select
          id="student-parent-id"
          value={parentId}
          onChange={(event) => {
            setParentId(event.target.value);
            setSubmitOk(false);
            setSubmitError(null);
          }}
          className="h-10 w-full rounded-md border border-neutral-200 bg-white px-3 text-sm text-rally-base outline-none focus:border-rally-cobalt-600 focus:ring-2 focus:ring-rally-cobalt-600/15"
          disabled={
            parentsLoading || parentsError || filteredParents.length === 0
          }
          required
        >
          <option value="">
            {parentsLoading
              ? "Loading parents..."
              : filteredParents.length === 0
                ? "No active parents found"
                : "Select a parent"}
          </option>
          {filteredParents.map((parent) => (
            <option key={parent.user_id} value={parent.user_id}>
              {parent.display_name} ({parent.email})
            </option>
          ))}
        </select>
      </Field>

      {selectedParent && (
        <div className="rounded-md border border-neutral-200 bg-neutral-50 p-3 text-sm">
          <div className="font-medium text-rally-ink">
            {selectedParent.display_name}
          </div>
          <div className="text-rally-muted">{selectedParent.email}</div>
          {selectedParent.phone && (
            <div className="text-rally-muted">{selectedParent.phone}</div>
          )}
        </div>
      )}

      <Field label="Reason" htmlFor="student-parent-reason">
        <input
          id="student-parent-reason"
          value={reason}
          onChange={(event) => setReason(event.target.value)}
          className="h-10 w-full rounded-md border border-neutral-200 bg-white px-3 text-sm text-rally-base outline-none focus:border-rally-cobalt-600 focus:ring-2 focus:ring-rally-cobalt-600/15"
          required
          maxLength={500}
        />
      </Field>

      {submitError && (
        <p
          role="alert"
          data-testid="admin-student-change-parent-error"
          className="rounded-md border border-red-200 bg-red-50 p-2 text-sm text-red-700"
        >
          {submitError}
        </p>
      )}
      {submitOk && (
        <p
          role="status"
          data-testid="admin-student-change-parent-ok"
          className="rounded-md border border-emerald-200 bg-emerald-50 p-2 text-sm text-emerald-800"
        >
          Parent account changed.
        </p>
      )}
      {warnings.length > 0 && (
        <div className="rounded-md border border-amber-200 bg-amber-50 p-2 text-sm text-amber-900">
          {warnings.map((warning) => (
            <div key={warning}>{warning}</div>
          ))}
        </div>
      )}

      <Button
        type="submit"
        variant="primary"
        size="sm"
        disabled={
          !canSubmit || mutation.isPending || parentsLoading || parentsError
        }
        icon={
          mutation.isPending ? (
            <RefreshCw className="size-3.5 animate-spin" />
          ) : undefined
        }
      >
        {mutation.isPending ? "Changing..." : "Change parent"}
      </Button>
    </form>
  );
}

function Field({
  label,
  htmlFor,
  children,
}: {
  label: string;
  htmlFor: string;
  children: React.ReactNode;
}) {
  return (
    <div className="space-y-1.5">
      <label
        htmlFor={htmlFor}
        className="font-mono text-[10px] font-bold uppercase tracking-overline text-rally-muted"
      >
        {label}
      </label>
      {children}
    </div>
  );
}
