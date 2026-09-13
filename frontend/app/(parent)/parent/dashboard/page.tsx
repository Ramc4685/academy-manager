"use client";

import { useMemo } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import {
  Activity,
  AlertCircle,
  AlertTriangle,
  BookOpen,
  CalendarDays,
  ChevronRight,
  ClipboardList,
  CreditCard,
  FileSignature,
  Mail,
  MapPin,
  Phone,
  Sparkles,
  Trophy,
  UserPlus,
} from "lucide-react";

import {
  getParentAcademy,
  getParentCurrentWaiver,
  listParentAttendance,
  listParentCredits,
  listParentEnrollments,
  listParentInvoices,
  listParentPayments,
  listParentProgress,
  type ParentAcademy,
  type ParentChild,
} from "@/lib/api/parent";
import {
  getParentHome,
  type ParentHomeBalance,
  type ParentHomeChild,
} from "@/lib/api/parent-home";
import { getParentProgressSummary } from "@/lib/api/curriculum";
import { resolveAcademyTimeZone } from "@/lib/format/academy-time";
import { nameGradient, nameInitial } from "@/lib/avatar-gradient";
import {
  attendanceCopy,
  balanceBannerCopy,
  buildParentHomeModel,
  milestoneCopy,
  nextSessionCopy,
  shouldShowBalanceBanner,
  type ParentHomeAction,
  type ParentHomeActivity,
} from "@/lib/parent-home";

const progressOverviewEnabled =
  process.env.NEXT_PUBLIC_SKILL_PROGRESS_OVERVIEW === "1";

export default function ParentDashboardPage() {
  const academyQuery = useQuery({
    queryKey: ["parent", "academy"],
    queryFn: getParentAcademy,
  });
  // One aggregated read backs the kid-first cards and the balance banner —
  // rendering N children off the per-resource endpoints would cost 2N round
  // trips on a phone. The queries below still feed the sections that stay.
  const homeQuery = useQuery({
    queryKey: ["parent", "home"],
    queryFn: getParentHome,
  });
  const enrollmentsQuery = useQuery({
    queryKey: ["parent", "enrollments"],
    queryFn: listParentEnrollments,
  });
  const attendanceQuery = useQuery({
    queryKey: ["parent", "attendance"],
    queryFn: listParentAttendance,
  });
  const progressNotesQuery = useQuery({
    queryKey: ["parent", "progress"],
    queryFn: listParentProgress,
  });
  const paymentsQuery = useQuery({
    queryKey: ["parent", "payments"],
    queryFn: listParentPayments,
  });
  const invoicesQuery = useQuery({
    queryKey: ["parent", "invoices"],
    queryFn: listParentInvoices,
  });
  const creditsQuery = useQuery({
    queryKey: ["parent", "credits"],
    queryFn: listParentCredits,
  });
  const waiverQuery = useQuery({
    queryKey: ["parent", "waivers", "current"],
    queryFn: getParentCurrentWaiver,
    retry: false,
  });
  const progressSummaryQuery = useQuery({
    queryKey: ["parent", "progress-summary", "default"],
    queryFn: () => getParentProgressSummary(),
    enabled: progressOverviewEnabled,
  });

  const homeChildren = useMemo(
    () => homeQuery.data?.children ?? [],
    [homeQuery.data],
  );
  const academyTimezone = homeQuery.data?.timezone ?? academyQuery.data?.timezone ?? null;

  // The retained sections (PrimaryActionCard, RecentActivityCard) still run
  // off buildParentHomeModel, which wants the ParentChild shape. The home
  // aggregate carries the only two fields those code paths read; the counts
  // it does not carry fed the deleted MetricGrid.
  const modelChildren = useMemo<ParentChild[]>(
    () =>
      homeChildren.map((child) => ({
        student_id: child.student_id,
        full_name: child.full_name,
        lifecycle: "active",
        active_session_count: 0,
        attended_count: 0,
        absent_count: 0,
      })),
    [homeChildren],
  );

  const model = useMemo(
    () =>
      buildParentHomeModel({
        children: modelChildren,
        enrollments: enrollmentsQuery.data?.enrollments ?? [],
        attendance: attendanceQuery.data?.records ?? [],
        notes: progressNotesQuery.data?.notes ?? [],
        payments: paymentsQuery.data?.payments ?? [],
        invoices: invoicesQuery.data?.invoices ?? [],
        credits: creditsQuery.data ?? null,
        waiver: waiverQuery.data ?? null,
        progressRows: progressSummaryQuery.data ?? [],
      }),
    [
      attendanceQuery.data,
      creditsQuery.data,
      enrollmentsQuery.data,
      invoicesQuery.data,
      modelChildren,
      paymentsQuery.data,
      progressNotesQuery.data,
      progressSummaryQuery.data,
      waiverQuery.data,
    ],
  );

  const optionalIssues = [
    attendanceQuery.isError ? "Attendance unavailable" : null,
    progressNotesQuery.isError ? "Coach notes unavailable" : null,
    paymentsQuery.isError ? "Payments unavailable" : null,
    creditsQuery.isError ? "Credits unavailable" : null,
    waiverQuery.isError ? "Waiver status unavailable" : null,
    progressSummaryQuery.isError ? "Skill progress unavailable" : null,
  ].filter(Boolean) as string[];

  const coreLoading = homeQuery.isLoading || academyQuery.isLoading;
  const balance = homeQuery.data?.balance ?? null;
  const showBanner = shouldShowBalanceBanner(balance);
  const hasChildren = homeChildren.length > 0;

  return (
    <section data-testid="parent-dashboard" className="space-y-4">
      {/*
        The kid-first Home has no visible page title — the child cards are the
        title. It still needs one h1 so the screen-reader rotor and the a11y
        audits have a document heading; the zero-children branch renders its
        own visible h1 inside RegistrationHero, so this one is hidden only
        when there are children to head.
      */}
      {hasChildren && <h1 className="sr-only">Home</h1>}
      {coreLoading ? (
        <DashboardSkeleton />
      ) : homeQuery.isError ? (
        <p
          data-testid="parent-home-error"
          className="rounded-xl border border-status-red-500/30 bg-status-red-50 px-4 py-3 text-sm font-semibold text-status-red-800"
        >
          We couldn&apos;t load your children right now. Pull down to refresh, or try again in a moment.
        </p>
      ) : (
        <>
          {showBanner && balance && <BalanceBanner balance={balance} />}
          {hasChildren ? (
            <ChildCardList items={homeChildren} timezone={academyTimezone} />
          ) : (
            <RegistrationHero academy={academyQuery.data} />
          )}
        </>
      )}

      {optionalIssues.length > 0 && <IssueStrip issues={optionalIssues} />}

      {hasChildren && (
        <>
          {/* The banner owns money now — a payment action would say it twice. */}
          {model.primaryAction.kind !== "payment" && (
            <PrimaryActionCard action={model.primaryAction} />
          )}
          <RecentActivityCard activity={model.recentActivity} academyTimezone={academyTimezone} />
        </>
      )}

      <RequestsCard />

      <AcademyContact academy={academyQuery.data} />
    </section>
  );
}

function DashboardSkeleton() {
  return (
    <div data-testid="parent-home-skeleton" className="space-y-3">
      <div className="h-32 rounded-2xl shimmer" />
      <div className="h-32 rounded-2xl shimmer" />
      <div className="h-28 rounded-xl shimmer" />
    </div>
  );
}

function BalanceBanner({ balance }: { balance: ParentHomeBalance }) {
  const { headline, detail } = balanceBannerCopy(balance);
  const failed = balance.payment_failed;
  const tone = failed
    ? "border-status-red-500/30 bg-status-red-50 text-status-red-800"
    : "border-status-amber-500/30 bg-status-amber-50 text-status-amber-800";
  const iconTone = failed ? "bg-status-red-500/15" : "bg-status-amber-500/15";
  const payTone = failed
    ? "bg-status-red-600 text-white"
    : "bg-status-amber-800 text-white";

  return (
    <div
      role="status"
      data-testid="parent-balance-banner"
      className={`flex items-center gap-3 rounded-xl border p-4 animate-fade-in-up ${tone}`}
    >
      <div className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-xl ${iconTone}`}>
        {failed ? <AlertTriangle size={18} /> : <CreditCard size={18} />}
      </div>
      <div className="min-w-0 flex-1">
        <p className="text-sm font-bold">{headline}</p>
        <p className="mt-0.5 text-xs opacity-80">{detail}</p>
      </div>
      <Link
        href="/parent/payments"
        data-testid="parent-balance-pay"
        className={`inline-flex min-h-touch min-w-touch shrink-0 items-center justify-center rounded-xl px-4 text-sm font-bold transition-all duration-200 active:scale-95 ${payTone}`}
      >
        Pay
      </Link>
    </div>
  );
}

function ChildCardList({
  items,
  timezone,
}: {
  items: ParentHomeChild[];
  timezone: string | null;
}) {
  return (
    <ul data-testid="parent-child-cards" className="space-y-3 stagger-children">
      {items.map((child) => (
        <li key={child.student_id}>
          <ChildCard child={child} timezone={timezone} />
        </li>
      ))}
    </ul>
  );
}

/**
 * One card per child, and the whole card is the tap target — a single link
 * into that child's Progress. No nested interactive elements: a link inside a
 * link is invalid and gives screen readers two overlapping targets.
 */
function ChildCard({
  child,
  timezone,
}: {
  child: ParentHomeChild;
  timezone: string | null;
}) {
  const next = nextSessionCopy(child.next_session, timezone);
  const milestone = milestoneCopy(child.latest_milestone, timezone);

  return (
    <Link
      href={`/parent/progress?child=${encodeURIComponent(child.student_id)}#skill-progress`}
      data-testid={`parent-child-card-${child.student_id}`}
      className="block rounded-2xl border border-rally-line bg-white p-4 animate-fade-in-up transition-all duration-200 hover:-translate-y-0.5 hover:shadow-md active:scale-[0.98]"
    >
      <div className="flex items-center gap-3">
        {/* Avatar gradient is a per-child hash, shared with the Children list. */}
        <span
          aria-hidden="true"
          className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl text-base font-bold text-white"
          style={{ background: nameGradient(child.full_name) }}
        >
          {nameInitial(child.full_name)}
        </span>
        {/* The child's name heads the card, so it is a real heading: the
            rotor's Headings list becomes a list of children. */}
        <h2 className="min-w-0 flex-1 truncate font-display text-lg font-bold text-rally-ink">
          {child.full_name}
        </h2>
        <ChevronRight className="shrink-0 text-rally-muted" size={18} />
      </div>

      <dl className="mt-3 space-y-2.5">
        <CardRow
          icon={<CalendarDays size={15} />}
          label="Next session"
          value={next ? next.when : "No upcoming sessions"}
          meta={
            next
              ? [next.where, child.next_session?.coach_name].filter(Boolean).join(" · ")
              : null
          }
        />
        <CardRow
          icon={<Trophy size={15} />}
          label="Attendance this month"
          value={attendanceCopy(child.attendance_this_month)}
          meta={null}
        />
        <CardRow
          icon={<Sparkles size={15} />}
          label="Latest milestone"
          value={milestone ?? "No milestones yet"}
          meta={null}
        />
      </dl>
    </Link>
  );
}

function CardRow({
  icon,
  label,
  value,
  meta,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
  meta: string | null;
}) {
  return (
    <div className="flex gap-2.5">
      <span className="mt-0.5 shrink-0 text-rally-cobalt-600">{icon}</span>
      <div className="min-w-0 flex-1">
        <dt className="text-[10px] font-bold uppercase tracking-widest text-rally-subtle">
          {label}
        </dt>
        <dd className="text-sm font-semibold text-rally-ink">{value}</dd>
        {meta && <p className="mt-0.5 truncate text-xs text-rally-muted">{meta}</p>}
      </div>
    </div>
  );
}

const PROGRESS_HERO_TEAL = "#0f766e";

function RegistrationHero({ academy }: { academy?: ParentAcademy }) {
  return (
    <div
      className="rounded-2xl p-5 text-white animate-fade-in-up"
      style={{ background: "linear-gradient(135deg,var(--rally-night) 0%,var(--rally-cobalt-hover) 100%)" }}
    >
      <div className="mb-6 flex items-center justify-between gap-3">
        <div>
          <p className="text-[10px] font-bold uppercase tracking-widest text-blue-100/70">
            {academy?.display_name ?? "Academy"}
          </p>
          <h1 className="mt-1 font-display text-2xl font-bold">
            Start your academy journey
          </h1>
        </div>
        <AcademyMark academy={academy} />
      </div>
      <p className="max-w-xs text-sm leading-6 text-blue-50/80">
        Register a child to see classes, coach notes, payments, and progress in
        one place.
      </p>
      <Link
        href="/parent/onboarding"
        className="mt-5 inline-flex min-h-touch items-center gap-2 rounded-xl bg-white px-4 text-sm font-bold text-rally-cobalt-700 transition-all duration-200 active:scale-95"
      >
        <UserPlus size={16} />
        Register a child
      </Link>
    </div>
  );
}

function AcademyMark({ academy }: { academy?: ParentAcademy }) {
  return (
    <div
      className="flex h-10 w-10 shrink-0 items-center justify-center overflow-hidden rounded-xl border-2 border-white/55 bg-white font-display text-base font-bold"
      style={{ color: PROGRESS_HERO_TEAL }}
    >
      {academy?.logo_url ? (
        <img
          src={academy.logo_url}
          alt=""
          className="h-full w-full object-cover"
        />
      ) : (
        (academy?.display_name?.[0] ?? "A").toUpperCase()
      )}
    </div>
  );
}

const ACTION_THEME: Record<ParentHomeAction["kind"], { icon: typeof FileSignature; className: string; iconClassName: string }> = {
  waiver: {
    icon: FileSignature,
    className: "bg-status-amber-50 border-status-amber-500/30 text-status-amber-800",
    iconClassName: "bg-status-amber-500/15",
  },
  credit: {
    icon: CreditCard,
    className: "bg-rally-cobalt-50 border-rally-cobalt-100 text-rally-cobalt-700",
    iconClassName: "bg-rally-cobalt-100",
  },
  payment: {
    icon: CreditCard,
    className: "bg-rally-cobalt-50 border-rally-cobalt-100 text-rally-cobalt-700",
    iconClassName: "bg-rally-cobalt-100",
  },
  progress: {
    icon: Trophy,
    className: "bg-status-green-50 border-status-green-500/30 text-status-green-800",
    iconClassName: "bg-status-green-500/15",
  },
  next_class: {
    icon: BookOpen,
    className: "bg-rally-cobalt-50 border-rally-cobalt-100 text-status-blue-800",
    iconClassName: "bg-rally-cobalt-100",
  },
  register: {
    icon: UserPlus,
    className: "bg-rally-volt-100 border-rally-volt-400/30 text-status-amber-800",
    iconClassName: "bg-rally-volt-100",
  },
};

function PrimaryActionCard({ action }: { action: ParentHomeAction }) {
  const theme = ACTION_THEME[action.kind] ?? ACTION_THEME.register;
  const Icon = theme.icon;
  return (
    <Link
      href={action.href as Parameters<typeof Link>[0]["href"]}
      className={`flex items-center gap-3 rounded-xl border p-4 animate-fade-in-up transition-all duration-200 hover:-translate-y-0.5 hover:shadow-md active:scale-[0.98] ${theme.className}`}
    >
      <div className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-xl ${theme.iconClassName}`}>
        <Icon size={18} />
      </div>
      <div className="min-w-0 flex-1">
        <p className="text-sm font-bold">{action.title}</p>
        <p className="mt-0.5 line-clamp-2 text-xs opacity-80">{action.body}</p>
      </div>
      <ChevronRight className="shrink-0" size={18} />
    </Link>
  );
}

function RecentActivityCard({
  activity,
  academyTimezone,
}: {
  activity: ParentHomeActivity[];
  academyTimezone: string | null;
}) {
  return (
    <div className="rounded-xl border border-rally-line bg-white p-4 animate-fade-in-up">
      <div className="mb-3 flex items-center justify-between gap-3">
        <div>
          <p className="text-[10px] font-bold uppercase tracking-widest text-rally-cobalt-600">
            Recent activity
          </p>
          <p className="mt-0.5 text-xs text-rally-muted">Notes, attendance, and billing updates</p>
        </div>
        <Activity size={18} className="text-rally-cobalt-600" />
      </div>
      {activity.length === 0 ? (
        <p className="rounded-lg bg-rally-paper px-3 py-3 text-sm text-rally-muted">
          Activity will appear after classes, notes, or payments are recorded.
        </p>
      ) : (
        <ul className="space-y-2">
          {activity.map((item) => (
            <li key={item.id} className="flex items-center gap-3 text-sm">
              {/* item.accent is a per-item computed color from lib/parent-home.ts — genuinely dynamic. */}
              <span className="h-2.5 w-2.5 shrink-0 rounded-full" style={{ background: item.accent }} />
              <div className="min-w-0 flex-1">
                <p className="truncate font-semibold text-rally-ink">{item.title}</p>
                <p className="truncate text-xs text-rally-muted">{item.body}</p>
              </div>
              <time className="shrink-0 text-[11px] text-rally-subtle">
                {formatShortDate(item.at, academyTimezone)}
              </time>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function RequestsCard() {
  return (
    <Link
      href="/parent/requests"
      className="flex items-center gap-3 rounded-xl border border-rally-line bg-white p-4 animate-fade-in-up transition-all duration-200 hover:-translate-y-0.5 hover:shadow-md active:scale-[0.98]"
    >
      <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-rally-cobalt-50 text-status-blue-800">
        <ClipboardList size={18} />
      </div>
      <div className="min-w-0 flex-1">
        <p className="text-sm font-bold text-rally-ink">Requests</p>
        <p className="mt-0.5 line-clamp-2 text-xs text-rally-muted">
          Report an absence, request a makeup, or ask for a trial class
        </p>
      </div>
      <ChevronRight className="shrink-0 text-rally-muted" size={18} />
    </Link>
  );
}

function AcademyContact({ academy }: { academy?: ParentAcademy }) {
  if (!academy || (!academy.contact_email && !academy.contact_phone && !academy.address)) {
    return null;
  }

  return (
    <div className="rounded-xl border border-rally-line bg-white p-4 animate-fade-in-up">
      <p className="text-[10px] font-bold uppercase tracking-widest text-rally-cobalt-600">Academy</p>
      <p className="mt-1 text-sm font-bold text-rally-ink">{academy.display_name}</p>
      <div className="mt-3 space-y-2 text-xs text-rally-muted">
        {academy.address && (
          <p className="flex gap-2">
            <MapPin className="mt-0.5 shrink-0" size={14} />
            <span>{academy.address}</span>
          </p>
        )}
        {academy.hours_text && <p>{academy.hours_text}</p>}
        <div className="flex flex-wrap gap-2 pt-1">
          {academy.contact_email && (
            <a
              href={`mailto:${academy.contact_email}`}
              className="inline-flex min-h-touch items-center gap-1.5 rounded-lg bg-rally-cobalt-600 px-3 text-xs font-bold text-white"
            >
              <Mail size={13} />
              Email
            </a>
          )}
          {academy.contact_phone && (
            <a
              href={`tel:${academy.contact_phone}`}
              className="inline-flex min-h-touch items-center gap-1.5 rounded-lg border border-status-green-500/30 bg-status-green-50 px-3 text-xs font-bold text-status-green-800"
            >
              <Phone size={13} />
              {academy.contact_phone}
            </a>
          )}
        </div>
      </div>
    </div>
  );
}

function IssueStrip({ issues }: { issues: string[] }) {
  return (
    <div className="flex flex-wrap gap-2">
      {issues.map((issue) => (
        <span
          key={issue}
          className="inline-flex items-center gap-1.5 rounded-full border border-status-amber-500/30 bg-status-amber-50 px-2.5 py-1 text-[11px] font-semibold text-status-amber-800"
        >
          <AlertCircle size={12} />
          {issue}
        </span>
      ))}
    </div>
  );
}

function formatShortDate(value: string, academyTimezone: string | null): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  const { timeZone } = resolveAcademyTimeZone(academyTimezone);
  return date.toLocaleDateString(undefined, { month: "short", day: "numeric", timeZone });
}
