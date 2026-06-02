"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";

import { getParentAcademy, listParentChildren, listParentEnrollments } from "@/lib/api/parent";

export default function ParentDashboardPage() {
  const { data: childrenData, isLoading: loadingChildren } = useQuery({
    queryKey: ["parent", "children"],
    queryFn: listParentChildren,
  });
  const { data: enrollmentsData, isLoading: loadingEnrollments } = useQuery({
    queryKey: ["parent", "enrollments"],
    queryFn: listParentEnrollments,
  });
  const { data: academy, isLoading: loadingAcademy } = useQuery({
    queryKey: ["parent", "academy"],
    queryFn: getParentAcademy,
  });

  const children = childrenData?.children ?? [];
  const activeEnrollments = (enrollmentsData?.enrollments ?? []).filter((e) => e.status === "active");

  return (
    <section data-testid="parent-dashboard" className="space-y-5">
      {/* Greeting */}
      <div className="animate-fade-in-up">
        <h1 className="font-display text-2xl font-bold tracking-tight" style={{ color: "var(--rally-ink)" }}>
          {loadingAcademy ? (
            <span className="inline-block h-7 w-40 rounded shimmer" />
          ) : (
            academy?.display_name ?? "Welcome"
          )}
        </h1>
        <p className="mt-0.5 text-sm" style={{ color: "var(--rally-muted)" }}>
          Your family&apos;s overview
        </p>
      </div>

      {/* Metric cards */}
      <div className="grid grid-cols-2 gap-3 stagger-children">
        <GradientMetric
          label="Students"
          value={loadingChildren ? null : children.length}
          gradient="linear-gradient(135deg,#2563eb 0%,#4f46e5 100%)"
          icon={
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" opacity="0.8">
              <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2" />
              <circle cx="9" cy="7" r="4" />
            </svg>
          }
        />
        <GradientMetric
          label="Enrollments"
          value={loadingEnrollments ? null : activeEnrollments.length}
          gradient="linear-gradient(135deg,#059669 0%,#0d9488 100%)"
          icon={
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" opacity="0.8">
              <polyline points="9 11 12 14 22 4" />
              <path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11" />
            </svg>
          }
        />
      </div>

      {/* Active sessions list */}
      {activeEnrollments.length > 0 && (
        <div
          className="rounded-xl p-4 animate-fade-in-up"
          style={{ background: "white", border: "1px solid var(--rally-line)", animationDelay: "80ms" }}
        >
          <p className="mb-3 text-[10px] font-bold uppercase tracking-widest" style={{ color: "var(--rally-cobalt)" }}>
            Active sessions
          </p>
          <ul className="space-y-2.5 stagger-children">
            {activeEnrollments.map((e) => (
              <li key={e.enrollment_id} className="flex items-center gap-2.5 animate-fade-in-up">
                <div
                  className="h-7 w-7 rounded-lg flex items-center justify-center text-xs font-bold text-white shrink-0"
                  style={{ background: nameGradient(e.student_name) }}
                >
                  {e.student_name[0]}
                </div>
                <span className="text-sm font-semibold flex-1" style={{ color: "var(--rally-ink)" }}>
                  {e.student_name}
                </span>
                <span
                  className="text-[11px] font-semibold rounded-full px-2 py-0.5 truncate max-w-[120px]"
                  style={{ background: "var(--rally-cobalt-soft)", color: "var(--rally-cobalt)" }}
                >
                  {e.session_title}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Quick links */}
      <div className="grid gap-2.5 stagger-children">
        <ActionCard href="/parent/children" title="My children" body="Sessions, attendance & details" accentColor="#4f46e5"
          icon={<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>}
        />
        <ActionCard href="/parent/progress" title="Progress" body="Notes and feedback from coaches" accentColor="#059669"
          icon={<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></svg>}
        />
        <ActionCard href="/parent/payments" title="Payments" body="Billing history and invoices" accentColor="#d97706"
          icon={<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="1" y="4" width="22" height="16" rx="2" ry="2"/><line x1="1" y1="10" x2="23" y2="10"/></svg>}
        />
        <ActionCard href="/parent/onboarding" title="Register a child" body="Start or resume onboarding" accentColor="#2563eb"
          icon={<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="16"/><line x1="8" y1="12" x2="16" y2="12"/></svg>}
        />
      </div>

      {/* Academy contact */}
      {!loadingAcademy && academy && (academy.contact_email || academy.contact_phone || academy.address) && (
        <div
          className="rounded-xl overflow-hidden animate-fade-in-up"
          style={{ background: "white", border: "1px solid var(--rally-line)" }}
        >
          <div className="px-4 py-3" style={{ background: "linear-gradient(135deg,#0a0f1c 0%,#0f1d38 100%)" }}>
            <p className="text-[10px] font-bold uppercase tracking-widest text-white/50">Contact &amp; info</p>
            <p className="text-sm font-semibold text-white mt-0.5">{academy.display_name}</p>
          </div>
          <div className="px-4 py-3 space-y-1 text-sm" style={{ color: "var(--rally-muted)" }}>
            {academy.address && <p>{academy.address}</p>}
            {academy.hours_text && <p>{academy.hours_text}</p>}
            {(academy.contact_email || academy.contact_phone) && (
              <div className="flex flex-wrap gap-2 pt-2">
                {academy.contact_email && (
                  <a
                    href={`mailto:${academy.contact_email}`}
                    className="inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-semibold text-white transition-all duration-150 active:scale-95"
                    style={{ background: "var(--rally-cobalt)" }}
                  >
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z"/><polyline points="22,6 12,13 2,6"/></svg>
                    Email
                  </a>
                )}
                {academy.contact_phone && (
                  <a
                    href={`tel:${academy.contact_phone}`}
                    className="inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-semibold transition-all duration-150 active:scale-95"
                    style={{ background: "#f0fdf4", color: "#059669", border: "1px solid #bbf7d0" }}
                  >
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07A19.5 19.5 0 0 1 4.69 13.1a19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 3.6 2.18h3a2 2 0 0 1 2 1.72c.127.96.361 1.903.7 2.81a2 2 0 0 1-.45 2.11L7.91 9.91a16 16 0 0 0 6.18 6.18l.95-.93a2 2 0 0 1 2.11-.45c.907.339 1.85.573 2.81.7A2 2 0 0 1 21.73 17z"/></svg>
                    {academy.contact_phone}
                  </a>
                )}
              </div>
            )}
          </div>
        </div>
      )}
    </section>
  );
}

function GradientMetric({ label, value, gradient, icon }: { label: string; value: number | null; gradient: string; icon: React.ReactNode }) {
  return (
    <div
      className="rounded-xl p-4 animate-fade-in-up transition-all duration-200 active:scale-95"
      style={{ background: gradient }}
    >
      <div className="flex items-start justify-between">
        <div>
          <p className="text-[10px] font-bold uppercase tracking-widest text-white/70">{label}</p>
          <p className="mt-1.5 font-display text-3xl font-bold text-white">
            {value === null ? (
              <span className="inline-block h-8 w-8 rounded shimmer opacity-40" />
            ) : (
              value
            )}
          </p>
        </div>
        <div className="rounded-lg p-2" style={{ background: "rgba(255,255,255,0.15)" }}>{icon}</div>
      </div>
    </div>
  );
}

function ActionCard({ href, title, body, accentColor, icon }: { href: string; title: string; body: string; accentColor: string; icon: React.ReactNode }) {
  return (
    <Link
      href={href as Parameters<typeof Link>[0]["href"]}
      className="flex items-center gap-3 rounded-xl p-3.5 animate-fade-in-up transition-all duration-200 hover:-translate-y-0.5 hover:shadow-md active:scale-[0.98]"
      style={{ background: "white", border: "1px solid var(--rally-line)", borderLeft: `3px solid ${accentColor}` }}
    >
      <div
        className="h-9 w-9 rounded-lg flex items-center justify-center shrink-0"
        style={{ background: `${accentColor}18`, color: accentColor }}
      >
        {icon}
      </div>
      <div className="min-w-0 flex-1">
        <p className="text-sm font-semibold" style={{ color: "var(--rally-ink)" }}>{title}</p>
        <p className="text-xs mt-0.5 truncate" style={{ color: "var(--rally-muted)" }}>{body}</p>
      </div>
      <svg className="ml-auto shrink-0" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" style={{ color: "var(--rally-subtle)" }}>
        <polyline points="9 18 15 12 9 6" />
      </svg>
    </Link>
  );
}

const GRADIENTS = [
  "linear-gradient(135deg,#2563eb,#4f46e5)",
  "linear-gradient(135deg,#059669,#0d9488)",
  "linear-gradient(135deg,#d97706,#f59e0b)",
  "linear-gradient(135deg,#7c3aed,#db2777)",
  "linear-gradient(135deg,#0891b2,#2563eb)",
];
function nameGradient(s: string) {
  let h = 0;
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) & 0xffffffff;
  return GRADIENTS[Math.abs(h) % GRADIENTS.length];
}
