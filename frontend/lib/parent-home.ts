import type {
  ParentAttendanceRecord,
  ParentChild,
  ParentCreditBalance,
  ParentEnrollment,
  ParentInvoice,
  ParentPayment,
  ParentProgressNote,
  ParentWaiverCurrentView,
} from "./api/parent";
import type { StudentProgressOverview } from "./api/curriculum";
import type {
  ParentHomeAttendance,
  ParentHomeBalance,
  ParentHomeMilestone,
  ParentHomeNextSession,
} from "./api/parent-home";

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
  /**
   * Ledger invoices, used to drop a stale "Payment needs attention" for a
   * failed payment whose invoice has since been voided or paid (#651).
   * Optional: callers without invoice data keep the payment-only behaviour.
   */
  invoices?: ParentInvoice[];
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
    childEnrollments.find((enrollment) => enrollment.status === "active") ?? null;
  const familyNotes = sortByDateDesc(input.notes, (note) => note.created_at);
  const familyAttendance = sortByDateDesc(
    input.attendance,
    (record) => record.marked_at,
  );
  const latestNote =
    familyNotes.find((note) => note.student_id === selectedChild.student_id) ?? null;

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
      children: input.children,
      selectedChild,
      progressRow,
      activeEnrollment,
      hasActiveEnrollment: input.enrollments.some(
        (enrollment) => enrollment.status === "active",
      ),
      credits: input.credits,
      payments: input.payments,
      invoices: input.invoices ?? [],
      waiver: input.waiver,
    }),
    // Home no longer has a child switcher, so "Recent activity" is the
    // family's — scoping it to the first child would silently hide every
    // other child's notes and absences under a family-wide subtitle.
    recentActivity: buildActivity({
      notes: familyNotes,
      attendance: familyAttendance,
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

const PAYMENT_ISSUE_STATUSES = new Set(["failed", "past_due", "requires_payment_method"]);
/** Invoice states where a failed attempt no longer needs the parent's attention. */
const SETTLED_INVOICE_STATUSES = new Set(["void", "paid"]);

/**
 * A failed/past-due payment still needs attention unless its invoice has
 * since been voided (enrollment cancelled/paused, #651) or paid, or the
 * parent has no active enrollment left to keep uninterrupted.
 */
export function findPaymentNeedingAttention({
  payments,
  invoices,
  hasActiveEnrollment,
}: {
  payments: ParentPayment[];
  invoices: ParentInvoice[];
  hasActiveEnrollment: boolean;
}): ParentPayment | null {
  if (!hasActiveEnrollment) return null;
  const invoiceStatusById = new Map(
    invoices.map((invoice) => [invoice.invoice_id, invoice.status] as const),
  );
  return (
    payments.find((payment) => {
      if (!PAYMENT_ISSUE_STATUSES.has(payment.status)) return false;
      const invoiceStatus = payment.invoice_id
        ? invoiceStatusById.get(payment.invoice_id)
        : undefined;
      return !(invoiceStatus && SETTLED_INVOICE_STATUSES.has(invoiceStatus));
    }) ?? null
  );
}

function choosePrimaryAction({
  children,
  selectedChild,
  progressRow,
  activeEnrollment,
  hasActiveEnrollment,
  credits,
  payments,
  invoices,
  waiver,
}: {
  children: ParentChild[];
  selectedChild: ParentChild;
  progressRow: StudentProgressOverview | null;
  activeEnrollment: ParentEnrollment | null;
  hasActiveEnrollment: boolean;
  credits: ParentCreditBalance | null;
  payments: ParentPayment[];
  invoices: ParentInvoice[];
  waiver: ParentWaiverCurrentView | null;
}): ParentHomeAction {
  // Any child with an unsigned waiver can be turned away at the door, and
  // Home has no child switcher to reveal the others — so the check runs over
  // the whole family, not just the first child.
  const familyStudentIds = new Set(children.map((child) => child.student_id));
  const unsignedWaiverStudent = waiver?.required
    ? waiver.students.find(
        (student) =>
          familyStudentIds.has(student.student_id) && student.status !== "signed",
      )
    : undefined;
  if (unsignedWaiverStudent) {
    return {
      kind: "waiver",
      title: "Waiver needs signature",
      body: `Sign the current academy waiver for ${unsignedWaiverStudent.student_name.split(" ")[0]} before the next class.`,
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

  const paymentIssue = findPaymentNeedingAttention({
    payments,
    invoices,
    hasActiveEnrollment,
  });
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

/* -------------------------------------------------------------------------
 * Kid-first home (slice 4) — pure copy helpers for the child cards and the
 * balance banner. Everything here is a pure function of the `/parent/home`
 * aggregate so it can be exercised from lib/parent-home.node-test.mjs.
 * ---------------------------------------------------------------------- */

/**
 * The banner is money-only: Home shows no billing content at all unless
 * something is actually due or a payment needs attention.
 */
export function shouldShowBalanceBanner(
  balance: ParentHomeBalance | null | undefined,
): boolean {
  if (!balance) return false;
  return balance.amount_due_cents > 0 || balance.payment_failed;
}

export interface BalanceBannerCopy {
  headline: string;
  detail: string;
}

/**
 * Plain-parent wording for the banner. A failed payment outranks an amount
 * due: fixing the payment method is what unblocks the money.
 */
export function balanceBannerCopy(
  balance: ParentHomeBalance,
  money: (cents: number, currency?: string) => string = formatMoney,
): BalanceBannerCopy {
  if (balance.payment_failed) {
    return {
      headline: "Payment didn't go through",
      detail: "Update your payment method to stay enrolled.",
    };
  }
  const headline = `${money(balance.amount_due_cents, balance.currency)} due`;
  const dueLabel = formatDueDate(balance.due_date);
  if (dueLabel) {
    return { headline, detail: `Due ${dueLabel}` };
  }
  if (balance.open_invoice_count > 1) {
    return { headline, detail: `${balance.open_invoice_count} open invoices` };
  }
  return { headline, detail: "Tap to pay your balance." };
}

export function attendanceCopy(attendance: ParentHomeAttendance | null | undefined): string {
  if (!attendance || attendance.total <= 0) {
    return "No sessions marked yet this month";
  }
  return `${attendance.present} of ${attendance.total} sessions this month`;
}

export interface NextSessionCopy {
  when: string;
  where: string;
}

/**
 * Day + time in the ACADEMY timezone (a travelling parent still sees the
 * class time the academy runs it at), plus the venue.
 */
export function nextSessionCopy(
  next: ParentHomeNextSession | null | undefined,
  timezone: string | null | undefined,
): NextSessionCopy | null {
  if (!next) return null;
  const instant = new Date(next.start_at);
  if (Number.isNaN(instant.getTime())) return null;
  const zone = resolveZone(timezone);
  const label = new Intl.DateTimeFormat("en-US", { timeZone: zone, timeZoneName: "short" })
    .formatToParts(instant)
    .find((part) => part.type === "timeZoneName")?.value ?? zone;
  const day = instant.toLocaleDateString("en-US", {
    weekday: "short",
    month: "short",
    day: "numeric",
    timeZone: zone,
  });
  const time = instant.toLocaleTimeString("en-US", {
    hour: "numeric",
    minute: "2-digit",
    timeZone: zone,
  });
  return {
    when: `${day} · ${time} ${label}`,
    where: next.location ?? "Venue to be confirmed",
  };
}

/**
 * Academy timezone when it is set and valid, else the viewer's.
 *
 * This mirrors `lib/format/academy-time.ts`'s `resolveAcademyTimeZone`
 * rather than importing it: this module is exercised by
 * `parent-home.node-test.mjs` under node's type stripping, which cannot
 * resolve an extensionless `.ts` specifier, and the tsconfig does not allow
 * writing the extension. Type-only imports (erased) are fine; value imports
 * are not.
 */
function resolveZone(timezone: string | null | undefined): string {
  const tz = timezone?.trim();
  if (tz) {
    try {
      new Intl.DateTimeFormat("en-US", { timeZone: tz });
      return tz;
    } catch {
      /* fall through to the viewer's zone */
    }
  }
  return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
}

/** `"Backhand lift · 2 days ago"`; null when the child has no milestone yet. */
export function milestoneCopy(
  milestone: ParentHomeMilestone | null | undefined,
  timezone?: string | null,
  now: Date = new Date(),
): string | null {
  if (!milestone) return null;
  const when = relativeDayLabel(milestone.at, timezone, now);
  return when ? `${milestone.label} · ${when}` : milestone.label;
}

/** "Sep 12" for a `YYYY-MM-DD` (or ISO instant) due date; "" when unusable. */
function formatDueDate(value: string | null | undefined): string {
  if (!value) return "";
  const dateOnly = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value.trim());
  // A date-only string must not be shifted by the viewer's zone (that turns
  // "due the 1st" into "due the 31st" west of UTC), so pin it to noon UTC.
  const instant = dateOnly
    ? new Date(Date.UTC(Number(dateOnly[1]), Number(dateOnly[2]) - 1, Number(dateOnly[3]), 12))
    : new Date(value);
  if (Number.isNaN(instant.getTime())) return "";
  return instant.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    timeZone: "UTC",
  });
}

/** "Today" / "Yesterday" / "4 days ago", falling back to "Sep 2". */
function relativeDayLabel(
  iso: string,
  timezone: string | null | undefined,
  now: Date,
): string {
  const instant = new Date(iso);
  if (Number.isNaN(instant.getTime())) return "";
  const timeZone = resolveZone(timezone);
  const days = calendarDayDiff(now, instant, timeZone);
  if (days === 0) return "Today";
  if (days === 1) return "Yesterday";
  if (days > 1 && days < 7) return `${days} days ago`;
  return instant.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    timeZone,
  });
}

/** Whole calendar days between two instants, counted in `timeZone`. */
function calendarDayDiff(later: Date, earlier: Date, timeZone: string): number {
  const a = calendarDayNumber(later, timeZone);
  const b = calendarDayNumber(earlier, timeZone);
  if (a === null || b === null) return Number.NaN;
  return a - b;
}

function calendarDayNumber(instant: Date, timeZone: string): number | null {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(instant);
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(parts);
  if (!match) return null;
  return (
    Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3])) / 86_400_000
  );
}
