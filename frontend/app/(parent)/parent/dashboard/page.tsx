"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import {
  Activity,
  AlertCircle,
  BookOpen,
  CalendarDays,
  ChevronRight,
  ClipboardList,
  CreditCard,
  FileSignature,
  Mail,
  MapPin,
  MessageSquare,
  Phone,
  Trophy,
  UserPlus,
} from "lucide-react";

import {
  getParentAcademy,
  getParentCurrentWaiver,
  listParentAttendance,
  listParentChildren,
  listParentCredits,
  listParentEnrollments,
  listParentPayments,
  listParentProgress,
  type ParentAcademy,
} from "@/lib/api/parent";
import { getParentProgressSummary } from "@/lib/api/curriculum";
import { resolveAcademyTimeZone } from "@/lib/format/academy-time";
import {
  buildParentHomeModel,
  type ParentHomeAction,
  type ParentHomeActivity,
  type ParentHomeMetric,
} from "@/lib/parent-home";

const progressOverviewEnabled =
  process.env.NEXT_PUBLIC_SKILL_PROGRESS_OVERVIEW === "1";

export default function ParentDashboardPage() {
  const [selectedChildId, setSelectedChildId] = useState<string | null>(null);

  const academyQuery = useQuery({
    queryKey: ["parent", "academy"],
    queryFn: getParentAcademy,
  });
  const childrenQuery = useQuery({
    queryKey: ["parent", "children"],
    queryFn: listParentChildren,
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

  const model = useMemo(
    () =>
      buildParentHomeModel({
        selectedChildId,
        children: childrenQuery.data?.children ?? [],
        enrollments: enrollmentsQuery.data?.enrollments ?? [],
        attendance: attendanceQuery.data?.records ?? [],
        notes: progressNotesQuery.data?.notes ?? [],
        payments: paymentsQuery.data?.payments ?? [],
        credits: creditsQuery.data ?? null,
        waiver: waiverQuery.data ?? null,
        progressRows: progressSummaryQuery.data ?? [],
      }),
    [
      attendanceQuery.data,
      childrenQuery.data,
      creditsQuery.data,
      enrollmentsQuery.data,
      paymentsQuery.data,
      progressNotesQuery.data,
      progressSummaryQuery.data,
      selectedChildId,
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

  const coreLoading = childrenQuery.isLoading || academyQuery.isLoading;

  return (
    <section data-testid="parent-dashboard" className="space-y-4">
      {coreLoading ? (
        <DashboardSkeleton />
      ) : model.selectedChild ? (
        <ProgressHero
          academy={academyQuery.data}
          model={model}
          selectedChildId={model.selectedChild.student_id}
          onSelectChild={setSelectedChildId}
          progressEnabled={progressOverviewEnabled}
        />
      ) : (
        <RegistrationHero academy={academyQuery.data} />
      )}

      {optionalIssues.length > 0 && <IssueStrip issues={optionalIssues} />}

      {model.selectedChild && (
        <>
          <MetricGrid metrics={model.metrics} />
          <div className="grid gap-3 sm:grid-cols-2">
            <LatestNoteCard note={model.latestNote} academyTimezone={academyQuery.data?.timezone ?? null} />
            <NextClassCard action={model.primaryAction} enrollmentTitle={model.nextEnrollment?.session_title ?? null} />
          </div>
          <PrimaryActionCard action={model.primaryAction} />
          <RecentActivityCard activity={model.recentActivity} academyTimezone={academyQuery.data?.timezone ?? null} />
        </>
      )}

      <RequestsCard />

      <AcademyContact academy={academyQuery.data} />
    </section>
  );
}

function DashboardSkeleton() {
  return (
    <div className="space-y-3">
      <div className="h-64 rounded-2xl shimmer" />
      <div className="grid grid-cols-3 gap-2">
        <div className="h-20 rounded-xl shimmer" />
        <div className="h-20 rounded-xl shimmer" />
        <div className="h-20 rounded-xl shimmer" />
      </div>
      <div className="h-28 rounded-xl shimmer" />
    </div>
  );
}

// The progress hero's teal->cobalt gradient is a decorative brand accent
// outside the two-hue (cobalt/volt) token system — kept inline per the
// DS4 plan's allowance for values a utility class can't reach.
const PROGRESS_HERO_GRADIENT = "linear-gradient(135deg,#042f2e 0%,#0f766e 42%,#2563eb 100%)";
const PROGRESS_HERO_TEAL = "#0f766e";

function ProgressHero({
  academy,
  model,
  selectedChildId,
  onSelectChild,
  progressEnabled,
}: {
  academy?: ParentAcademy;
  model: ReturnType<typeof buildParentHomeModel>;
  selectedChildId: string;
  onSelectChild: (studentId: string) => void;
  progressEnabled: boolean;
}) {
  const child = model.selectedChild;
  if (!child) return null;

  return (
    <div
      className="overflow-hidden rounded-2xl animate-fade-in-up shadow-[0_18px_45px_rgba(15,23,42,0.18)]"
      style={{ background: PROGRESS_HERO_GRADIENT }}
    >
      <div className="px-4 py-4 text-white">
        <div className="mb-4 flex items-center justify-between gap-3">
          <div className="min-w-0">
            <p className="text-[10px] font-bold uppercase tracking-widest text-emerald-100/80">
              {academy?.display_name ?? "Academy"}
            </p>
            <h1 className="mt-1 truncate font-display text-[22px] font-bold leading-tight">
              Family progress
            </h1>
          </div>
          <AcademyMark academy={academy} />
        </div>

        <div className="mb-4 flex gap-2 overflow-x-auto pb-1">
          {model.childOptions.map((option) => {
            const active = option.student_id === selectedChildId;
            return (
              <button
                key={option.student_id}
                type="button"
                onClick={() => onSelectChild(option.student_id)}
                className={`min-h-touch shrink-0 rounded-full px-3 text-xs font-bold transition-all duration-200 active:scale-95 ${
                  active ? "bg-white" : "bg-white/14 text-white"
                }`}
                style={active ? { color: PROGRESS_HERO_TEAL } : undefined}
              >
                {firstName(option.full_name)}
              </button>
            );
          })}
          <Link
            href="/parent/onboarding"
            className="min-h-touch shrink-0 rounded-full bg-white/10 px-3 text-xs font-bold text-emerald-100 transition-all duration-200 active:scale-95"
          >
            + Add
          </Link>
        </div>

        <div className="flex items-center gap-4">
          <div className="flex h-[72px] w-[72px] shrink-0 items-center justify-center rounded-2xl border border-white/22 bg-white/16 text-3xl font-bold hero-pop">
            {child.full_name[0]?.toUpperCase() ?? "S"}
          </div>
          <div className="min-w-0 flex-1">
            <p className="font-display text-[25px] font-bold leading-tight sm:text-[29px]">
              {model.hero.title}
            </p>
            <p className="mt-1.5 truncate text-xs font-medium text-emerald-50/85">
              {model.hero.subtitle}
            </p>
            <div className="mt-3 h-2 overflow-hidden rounded-full bg-white/18">
              <div
                className="h-full rounded-full progress-fill"
                style={{ width: `${model.hero.percent ?? 0}%`, background: "var(--rally-volt)" }}
              />
            </div>
            {!progressEnabled && (
              <p className="mt-2 text-[11px] font-medium text-emerald-50/70">
                Skill pathway preview appears after progress is enabled.
              </p>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

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

const METRIC_TONE_CLASS: Record<ParentHomeMetric["tone"], string> = {
  green: "text-status-green-800",
  amber: "text-status-amber-800",
  blue: "text-rally-cobalt-600",
};

function MetricGrid({ metrics }: { metrics: ParentHomeMetric[] }) {
  return (
    <div className="grid grid-cols-3 gap-2 stagger-children">
      {metrics.map((metric) => (
        <div
          key={metric.label}
          className="rounded-xl border border-rally-line bg-white px-3 py-3 text-center animate-fade-in-up"
        >
          <p className={`font-display text-xl font-bold ${METRIC_TONE_CLASS[metric.tone] ?? METRIC_TONE_CLASS.blue}`}>
            {metric.value}
          </p>
          <p className="mt-0.5 text-[10px] font-semibold text-rally-muted">{metric.label}</p>
        </div>
      ))}
    </div>
  );
}

type AccentKey = "green" | "cobalt";

const INFO_CARD_ACCENT: Record<AccentKey, { overline: string; iconBg: string; iconText: string; borderLeft: string }> = {
  green: {
    overline: "text-status-green-800",
    iconBg: "bg-status-green-50",
    iconText: "text-status-green-800",
    borderLeft: "border-l-status-green-500",
  },
  cobalt: {
    overline: "text-rally-cobalt-600",
    iconBg: "bg-rally-cobalt-50",
    iconText: "text-rally-cobalt-600",
    borderLeft: "border-l-rally-cobalt-600",
  },
};

function LatestNoteCard({
  note,
  academyTimezone,
}: {
  note: ReturnType<typeof buildParentHomeModel>["latestNote"];
  academyTimezone: string | null;
}) {
  return (
    <InfoCard
      overline="Latest coach note"
      title={note ? "Coach feedback" : "Notes will appear here"}
      body={note?.body ?? "Coach updates and encouragement will show up after class."}
      meta={note ? `${note.coach_name ?? "Coach"} · ${formatShortDate(note.created_at, academyTimezone)}` : "Progress"}
      icon={<MessageSquare size={17} />}
      accent="green"
      href="/parent/progress"
    />
  );
}

function NextClassCard({
  action,
  enrollmentTitle,
}: {
  action: ParentHomeAction;
  enrollmentTitle: string | null;
}) {
  const isNext = action.kind === "next_class" || Boolean(enrollmentTitle);
  return (
    <InfoCard
      overline="Next up"
      title={isNext ? "Class context" : "Stay on track"}
      body={enrollmentTitle ?? action.body}
      meta={isNext ? "Current enrollment" : action.title}
      icon={<CalendarDays size={17} />}
      accent="cobalt"
      href={isNext ? "/parent/children" : action.href}
    />
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

function InfoCard({
  overline,
  title,
  body,
  meta,
  icon,
  accent,
  href,
}: {
  overline: string;
  title: string;
  body: string;
  meta: string;
  icon: React.ReactNode;
  accent: AccentKey;
  href: string;
}) {
  const theme = INFO_CARD_ACCENT[accent];
  return (
    <Link
      href={href as Parameters<typeof Link>[0]["href"]}
      className={`block rounded-xl border border-rally-line border-l-4 bg-white p-4 animate-fade-in-up transition-all duration-200 hover:-translate-y-0.5 hover:shadow-md active:scale-[0.98] ${theme.borderLeft}`}
    >
      <div className="mb-3 flex items-center justify-between gap-3">
        <p className={`text-[10px] font-bold uppercase tracking-widest ${theme.overline}`}>{overline}</p>
        <span className={`flex h-8 w-8 items-center justify-center rounded-lg ${theme.iconBg} ${theme.iconText}`}>
          {icon}
        </span>
      </div>
      <p className="truncate text-sm font-bold text-rally-ink">{title}</p>
      <p className="mt-1 line-clamp-2 text-xs leading-5 text-rally-muted">{body}</p>
      <p className="mt-2 text-[11px] font-semibold text-rally-subtle">{meta}</p>
    </Link>
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

function firstName(name: string): string {
  return name.trim().split(/\s+/)[0] || name;
}

function formatShortDate(value: string, academyTimezone: string | null): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  const { timeZone } = resolveAcademyTimeZone(academyTimezone);
  return date.toLocaleDateString(undefined, { month: "short", day: "numeric", timeZone });
}
