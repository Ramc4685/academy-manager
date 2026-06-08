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
            <LatestNoteCard note={model.latestNote} />
            <NextClassCard action={model.primaryAction} enrollmentTitle={model.nextEnrollment?.session_title ?? null} />
          </div>
          <PrimaryActionCard action={model.primaryAction} />
          <RecentActivityCard activity={model.recentActivity} />
        </>
      )}

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
      className="overflow-hidden rounded-2xl animate-fade-in-up"
      style={{
        background: "linear-gradient(135deg,#042f2e 0%,#0f766e 42%,#2563eb 100%)",
        boxShadow: "0 18px 45px rgba(15,23,42,0.18)",
      }}
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
                className="min-h-touch shrink-0 rounded-full px-3 text-xs font-bold transition-all duration-200 active:scale-95"
                style={
                  active
                    ? { background: "white", color: "#0f766e" }
                    : { background: "rgba(255,255,255,0.14)", color: "white" }
                }
              >
                {firstName(option.full_name)}
              </button>
            );
          })}
          <Link
            href="/parent/onboarding"
            className="min-h-touch shrink-0 rounded-full px-3 text-xs font-bold transition-all duration-200 active:scale-95"
            style={{ background: "rgba(255,255,255,0.1)", color: "#d1fae5" }}
          >
            + Add
          </Link>
        </div>

        <div className="flex items-center gap-4">
          <div
            className="flex h-[72px] w-[72px] shrink-0 items-center justify-center rounded-2xl border text-3xl font-bold hero-pop"
            style={{
              background: "rgba(255,255,255,0.16)",
              borderColor: "rgba(255,255,255,0.22)",
            }}
          >
            {child.full_name[0]?.toUpperCase() ?? "S"}
          </div>
          <div className="min-w-0 flex-1">
            <p className="font-display text-[25px] font-bold leading-tight sm:text-[29px]">
              {model.hero.title}
            </p>
            <p className="mt-1.5 truncate text-xs font-medium text-emerald-50/85">
              {model.hero.subtitle}
            </p>
            <div
              className="mt-3 h-2 overflow-hidden rounded-full"
              style={{ background: "rgba(255,255,255,0.18)" }}
            >
              <div
                className="h-full rounded-full progress-fill"
                style={{
                  width: `${model.hero.percent ?? 0}%`,
                  background: "var(--rally-volt)",
                }}
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
      className="rounded-2xl p-5 animate-fade-in-up"
      style={{
        background: "linear-gradient(135deg,#0a0f1c 0%,#1d4ed8 100%)",
        color: "white",
      }}
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
        className="mt-5 inline-flex min-h-touch items-center gap-2 rounded-xl bg-white px-4 text-sm font-bold text-blue-700 transition-all duration-200 active:scale-95"
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
      className="flex h-10 w-10 shrink-0 items-center justify-center overflow-hidden rounded-xl border-2 bg-white font-display text-base font-bold"
      style={{ color: "#0f766e", borderColor: "rgba(255,255,255,0.55)" }}
    >
      {academy?.logo_url ? (
        // eslint-disable-next-line @next/next/no-img-element
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

function MetricGrid({ metrics }: { metrics: ParentHomeMetric[] }) {
  return (
    <div className="grid grid-cols-3 gap-2 stagger-children">
      {metrics.map((metric) => (
        <div
          key={metric.label}
          className="rounded-xl border bg-white px-3 py-3 text-center animate-fade-in-up"
          style={{ borderColor: "var(--rally-line)" }}
        >
          <p
            className="font-display text-xl font-bold"
            style={{ color: metricColor(metric.tone) }}
          >
            {metric.value}
          </p>
          <p className="mt-0.5 text-[10px] font-semibold" style={{ color: "var(--rally-muted)" }}>
            {metric.label}
          </p>
        </div>
      ))}
    </div>
  );
}

function LatestNoteCard({ note }: { note: ReturnType<typeof buildParentHomeModel>["latestNote"] }) {
  return (
    <InfoCard
      overline="Latest coach note"
      title={note ? "Coach feedback" : "Notes will appear here"}
      body={note?.body ?? "Coach updates and encouragement will show up after class."}
      meta={note ? `${note.coach_name ?? "Coach"} · ${formatShortDate(note.created_at)}` : "Progress"}
      icon={<MessageSquare size={17} />}
      accent="#059669"
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
      accent="#2563eb"
      href={isNext ? "/parent/children" : action.href}
    />
  );
}

function PrimaryActionCard({ action }: { action: ParentHomeAction }) {
  const theme = actionTheme(action.kind);
  const Icon = theme.icon;
  return (
    <Link
      href={action.href as Parameters<typeof Link>[0]["href"]}
      className="flex items-center gap-3 rounded-xl border p-4 animate-fade-in-up transition-all duration-200 hover:-translate-y-0.5 hover:shadow-md active:scale-[0.98]"
      style={{
        background: theme.background,
        borderColor: theme.border,
        color: theme.color,
      }}
    >
      <div
        className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl"
        style={{ background: theme.iconBackground }}
      >
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

function RecentActivityCard({ activity }: { activity: ParentHomeActivity[] }) {
  return (
    <div
      className="rounded-xl border bg-white p-4 animate-fade-in-up"
      style={{ borderColor: "var(--rally-line)" }}
    >
      <div className="mb-3 flex items-center justify-between gap-3">
        <div>
          <p className="text-[10px] font-bold uppercase tracking-widest" style={{ color: "var(--rally-cobalt)" }}>
            Recent activity
          </p>
          <p className="mt-0.5 text-xs" style={{ color: "var(--rally-muted)" }}>
            Notes, attendance, and billing updates
          </p>
        </div>
        <Activity size={18} style={{ color: "var(--rally-cobalt)" }} />
      </div>
      {activity.length === 0 ? (
        <p className="rounded-lg px-3 py-3 text-sm" style={{ background: "var(--rally-paper)", color: "var(--rally-muted)" }}>
          Activity will appear after classes, notes, or payments are recorded.
        </p>
      ) : (
        <ul className="space-y-2">
          {activity.map((item) => (
            <li key={item.id} className="flex items-center gap-3 text-sm">
              <span
                className="h-2.5 w-2.5 shrink-0 rounded-full"
                style={{ background: item.accent }}
              />
              <div className="min-w-0 flex-1">
                <p className="truncate font-semibold" style={{ color: "var(--rally-ink)" }}>
                  {item.title}
                </p>
                <p className="truncate text-xs" style={{ color: "var(--rally-muted)" }}>
                  {item.body}
                </p>
              </div>
              <time className="shrink-0 text-[11px]" style={{ color: "var(--rally-subtle)" }}>
                {formatShortDate(item.at)}
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
  accent: string;
  href: string;
}) {
  return (
    <Link
      href={href as Parameters<typeof Link>[0]["href"]}
      className="block rounded-xl border bg-white p-4 animate-fade-in-up transition-all duration-200 hover:-translate-y-0.5 hover:shadow-md active:scale-[0.98]"
      style={{ borderColor: "var(--rally-line)", borderLeft: `4px solid ${accent}` }}
    >
      <div className="mb-3 flex items-center justify-between gap-3">
        <p className="text-[10px] font-bold uppercase tracking-widest" style={{ color: accent }}>
          {overline}
        </p>
        <span
          className="flex h-8 w-8 items-center justify-center rounded-lg"
          style={{ background: `${accent}18`, color: accent }}
        >
          {icon}
        </span>
      </div>
      <p className="truncate text-sm font-bold" style={{ color: "var(--rally-ink)" }}>
        {title}
      </p>
      <p className="mt-1 line-clamp-2 text-xs leading-5" style={{ color: "var(--rally-muted)" }}>
        {body}
      </p>
      <p className="mt-2 text-[11px] font-semibold" style={{ color: "var(--rally-subtle)" }}>
        {meta}
      </p>
    </Link>
  );
}

function AcademyContact({ academy }: { academy?: ParentAcademy }) {
  if (!academy || (!academy.contact_email && !academy.contact_phone && !academy.address)) {
    return null;
  }

  return (
    <div
      className="rounded-xl border bg-white p-4 animate-fade-in-up"
      style={{ borderColor: "var(--rally-line)" }}
    >
      <p className="text-[10px] font-bold uppercase tracking-widest" style={{ color: "var(--rally-cobalt)" }}>
        Academy
      </p>
      <p className="mt-1 text-sm font-bold" style={{ color: "var(--rally-ink)" }}>
        {academy.display_name}
      </p>
      <div className="mt-3 space-y-2 text-xs" style={{ color: "var(--rally-muted)" }}>
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
              className="inline-flex min-h-touch items-center gap-1.5 rounded-lg px-3 text-xs font-bold text-white"
              style={{ background: "var(--rally-cobalt)" }}
            >
              <Mail size={13} />
              Email
            </a>
          )}
          {academy.contact_phone && (
            <a
              href={`tel:${academy.contact_phone}`}
              className="inline-flex min-h-touch items-center gap-1.5 rounded-lg border px-3 text-xs font-bold"
              style={{
                background: "#f0fdf4",
                borderColor: "#bbf7d0",
                color: "#047857",
              }}
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
          className="inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px] font-semibold"
          style={{ background: "#fff7ed", color: "#9a3412", border: "1px solid #fed7aa" }}
        >
          <AlertCircle size={12} />
          {issue}
        </span>
      ))}
    </div>
  );
}

function actionTheme(kind: ParentHomeAction["kind"]) {
  switch (kind) {
    case "waiver":
      return {
        icon: FileSignature,
        background: "#fff7ed",
        border: "#fed7aa",
        color: "#9a3412",
        iconBackground: "#fed7aa",
      };
    case "credit":
    case "payment":
      return {
        icon: CreditCard,
        background: "#eff6ff",
        border: "#bfdbfe",
        color: "#1d4ed8",
        iconBackground: "#dbeafe",
      };
    case "progress":
      return {
        icon: Trophy,
        background: "#f0fdf4",
        border: "#bbf7d0",
        color: "#047857",
        iconBackground: "#dcfce7",
      };
    case "next_class":
      return {
        icon: BookOpen,
        background: "#eef2ff",
        border: "#c7d2fe",
        color: "#4338ca",
        iconBackground: "#e0e7ff",
      };
    case "register":
    default:
      return {
        icon: UserPlus,
        background: "#fef9c3",
        border: "#fde68a",
        color: "#92400e",
        iconBackground: "#fde68a",
      };
  }
}

function metricColor(tone: ParentHomeMetric["tone"]): string {
  if (tone === "green") return "#059669";
  if (tone === "amber") return "#d97706";
  return "var(--rally-cobalt)";
}

function firstName(name: string): string {
  return name.trim().split(/\s+/)[0] || name;
}

function formatShortDate(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}
