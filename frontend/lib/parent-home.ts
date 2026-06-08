import type {
  ParentAttendanceRecord,
  ParentChild,
  ParentCreditBalance,
  ParentEnrollment,
  ParentPayment,
  ParentProgressNote,
  ParentWaiverCurrentView,
} from "./api/parent";
import type { StudentProgressOverview } from "./api/curriculum";

export type ParentHomeActionKind =
  | "register"
  | "waiver"
  | "credit"
  | "payment"
  | "progress"
  | "next_class";

export interface ParentHomeAction {
  kind: ParentHomeActionKind;
  title: string;
  body: string;
  href: string;
}

export interface ParentHomeActivity {
  id: string;
  kind: "note" | "attendance" | "payment";
  title: string;
  body: string;
  at: string;
  accent: string;
}

export interface ParentHomeMetric {
  label: string;
  value: string;
  tone: "green" | "blue" | "amber";
}

export interface ParentHomeHero {
  title: string;
  subtitle: string;
  percent: number | null;
  progressRow: StudentProgressOverview | null;
}

export interface ParentHomeInput {
  selectedChildId?: string | null;
  children: ParentChild[];
  enrollments: ParentEnrollment[];
  attendance: ParentAttendanceRecord[];
  notes: ParentProgressNote[];
  payments: ParentPayment[];
  credits: ParentCreditBalance | null;
  waiver: ParentWaiverCurrentView | null;
  progressRows: StudentProgressOverview[];
}

export interface ParentHomeModel {
  selectedChild: ParentChild | null;
  childOptions: ParentChild[];
  hero: ParentHomeHero;
  metrics: ParentHomeMetric[];
  latestNote: ParentProgressNote | null;
  nextEnrollment: ParentEnrollment | null;
  primaryAction: ParentHomeAction;
  recentActivity: ParentHomeActivity[];
}

export function buildParentHomeModel(input: ParentHomeInput): ParentHomeModel {
  const selectedChild =
    input.children.find((child) => child.student_id === input.selectedChildId) ??
    input.children[0] ??
    null;

  if (!selectedChild) {
    return {
      selectedChild: null,
      childOptions: [],
      hero: {
        title: "Start your academy journey",
        subtitle: "Register a child to see classes, progress, and coach updates here.",
        percent: null,
        progressRow: null,
      },
      metrics: [
        { label: "Students", value: "0", tone: "blue" },
        { label: "Progress", value: "New", tone: "green" },
        { label: "Actions", value: "1", tone: "amber" },
      ],
      latestNote: null,
      nextEnrollment: null,
      primaryAction: {
        kind: "register",
        title: "Register a child",
        body: "Add your first student and choose a session.",
        href: "/parent/onboarding",
      },
      recentActivity: [],
    };
  }

  const progressRow =
    input.progressRows.find((row) => row.student_id === selectedChild.student_id) ??
    null;
  const percent = progressRow
    ? progressPercent(progressRow.total_skills_passed, progressRow.total_skill_count)
    : null;
  const childEnrollments = input.enrollments.filter(
    (enrollment) => enrollment.student_id === selectedChild.student_id,
  );
  const activeEnrollment =
    childEnrollments.find((enrollment) => enrollment.status === "active") ??
    childEnrollments[0] ??
    null;
  const childNotes = sortByDateDesc(
    input.notes.filter((note) => note.student_id === selectedChild.student_id),
    (note) => note.created_at,
  );
  const childAttendance = sortByDateDesc(
    input.attendance.filter((record) => record.student_id === selectedChild.student_id),
    (record) => record.marked_at,
  );
  const latestNote = childNotes[0] ?? null;

  return {
    selectedChild,
    childOptions: input.children,
    hero: {
      title:
        percent === null
          ? "Progress is getting ready"
          : `${percent}% complete`,
      subtitle:
        progressRow?.current_level_name ??
        activeEnrollment?.session_title ??
        "First skills will appear after coach assessment.",
      percent,
      progressRow,
    },
    metrics: buildMetrics(selectedChild, progressRow),
    latestNote,
    nextEnrollment: activeEnrollment,
    primaryAction: choosePrimaryAction({
      selectedChild,
      progressRow,
      activeEnrollment,
      credits: input.credits,
      payments: input.payments,
      waiver: input.waiver,
    }),
    recentActivity: buildActivity({
      notes: childNotes,
      attendance: childAttendance,
      payments: input.payments,
    }),
  };
}

export function progressPercent(done: number, total: number): number | null {
  if (total <= 0) return null;
  return Math.round((done / total) * 100);
}

export function formatMoney(cents: number, currency = "USD"): string {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: currency.toUpperCase(),
  }).format(cents / 100);
}

function buildMetrics(
  child: ParentChild,
  progressRow: StudentProgressOverview | null,
): ParentHomeMetric[] {
  if (progressRow && progressRow.total_skill_count > 0) {
    return [
      {
        label: "Mastered",
        value: String(progressRow.total_skills_passed),
        tone: "green",
      },
      {
        label: "Learning",
        value: String(progressRow.in_progress_count),
        tone: "blue",
      },
      {
        label: "Ready",
        value: String(progressRow.test_ready_count),
        tone: "amber",
      },
    ];
  }

  const totalAttendance = child.attended_count + child.absent_count;
  const attendancePct = progressPercent(child.attended_count, totalAttendance);
  return [
    {
      label: "Sessions",
      value: String(child.active_session_count),
      tone: "blue",
    },
    {
      label: "Present",
      value: String(child.attended_count),
      tone: "green",
    },
    {
      label: "Attendance",
      value: attendancePct === null ? "New" : `${attendancePct}%`,
      tone: "amber",
    },
  ];
}

function choosePrimaryAction({
  selectedChild,
  progressRow,
  activeEnrollment,
  credits,
  payments,
  waiver,
}: {
  selectedChild: ParentChild;
  progressRow: StudentProgressOverview | null;
  activeEnrollment: ParentEnrollment | null;
  credits: ParentCreditBalance | null;
  payments: ParentPayment[];
  waiver: ParentWaiverCurrentView | null;
}): ParentHomeAction {
  const waiverStudent = waiver?.students.find(
    (student) => student.student_id === selectedChild.student_id,
  );
  if (waiver?.required && waiverStudent && waiverStudent.status !== "signed") {
    return {
      kind: "waiver",
      title: "Waiver needs signature",
      body: "Sign the current academy waiver before the next class.",
      href: "/parent/waivers",
    };
  }

  if ((credits?.balance_cents ?? 0) > 0) {
    return {
      kind: "credit",
      title: "Credit available",
      body: `${formatMoney(credits?.balance_cents ?? 0)} will apply to your next invoice.`,
      href: "/parent/payments",
    };
  }

  const paymentIssue = payments.find((payment) =>
    ["failed", "past_due", "requires_payment_method"].includes(payment.status),
  );
  if (paymentIssue) {
    return {
      kind: "payment",
      title: "Payment needs attention",
      body: "Review billing so enrollment stays uninterrupted.",
      href: "/parent/payments",
    };
  }

  if (progressRow) {
    return {
      kind: "progress",
      title: "Review progress",
      body: `${selectedChild.full_name.split(" ")[0]} has ${progressRow.total_skills_passed} skills mastered.`,
      href: "/parent/progress",
    };
  }

  if (activeEnrollment) {
    return {
      kind: "next_class",
      title: "Next class",
      body: activeEnrollment.session_title,
      href: "/parent/children",
    };
  }

  return {
    kind: "register",
    title: "Choose a session",
    body: "Finish enrollment to start tracking progress.",
    href: "/parent/onboarding",
  };
}

function buildActivity({
  notes,
  attendance,
  payments,
}: {
  notes: ParentProgressNote[];
  attendance: ParentAttendanceRecord[];
  payments: ParentPayment[];
}): ParentHomeActivity[] {
  const activity: ParentHomeActivity[] = [];
  const latestNote = notes[0];
  if (latestNote) {
    activity.push({
      id: `note-${latestNote.note_id}`,
      kind: "note",
      title: "Coach note added",
      body: latestNote.body,
      at: latestNote.created_at,
      accent: "#7c3aed",
    });
  }

  const latestAttendance = attendance[0];
  if (latestAttendance) {
    activity.push({
      id: `attendance-${latestAttendance.attendance_id}`,
      kind: "attendance",
      title: attendanceTitle(latestAttendance.status),
      body: latestAttendance.session_title,
      at: latestAttendance.marked_at,
      accent: latestAttendance.status === "absent" ? "#dc2626" : "#059669",
    });
  }

  const latestPayment = sortByDateDesc(payments, (payment) => payment.created_at)[0];
  if (latestPayment) {
    activity.push({
      id: `payment-${latestPayment.payment_id}`,
      kind: "payment",
      title: paymentTitle(latestPayment.status),
      body: formatMoney(latestPayment.amount_cents, latestPayment.currency),
      at: latestPayment.created_at,
      accent: latestPayment.status === "succeeded" ? "#2563eb" : "#d97706",
    });
  }

  return sortByDateDesc(activity, (item) => item.at).slice(0, 3);
}

function attendanceTitle(status: string): string {
  if (status === "absent") return "Marked absent";
  if (status === "late") return "Arrived late";
  return "Attended class";
}

function paymentTitle(status: string): string {
  if (status === "succeeded") return "Payment succeeded";
  if (status === "failed") return "Payment failed";
  if (status === "refunded") return "Payment refunded";
  return "Payment updated";
}

function sortByDateDesc<T>(items: T[], getDate: (item: T) => string): T[] {
  return [...items].sort(
    (a, b) => new Date(getDate(b)).getTime() - new Date(getDate(a)).getTime(),
  );
}
