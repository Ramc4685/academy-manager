import type { Route } from "next";
import Link from "next/link";
import type { ParentProgressJourney } from "@/lib/api/parent";
import type { SkillCertificate } from "@/lib/api/curriculum";
import { levelColorName, levelSwatch } from "@/lib/level-color";

// Presentational pieces of the parent progress journey (design: owner canvas
// "Parent · how far along"). Data shaping lives in the BFF; these only render.

type Journey = ParentProgressJourney;
type JourneyWin = Journey["recent_wins"][number];

/** The printable certificate screen; it needs the child to check ownership. */
export function certificateHref(certId: string, studentId: string): Route {
  return `/parent/progress/certificates/${encodeURIComponent(certId)}?child=${encodeURIComponent(studentId)}` as Route;
}

export function LevelStrip({ firstName, journey }: { firstName: string; journey: Journey }) {
  const current = journey.current_level;
  return (
    <div className="rounded-2xl px-4 pt-4 pb-3 bg-rally-ink text-white">
      <p className="text-xs font-bold uppercase tracking-chip text-rally-volt-300">
        {firstName}&apos;s badminton journey
      </p>
      <p className="font-display text-2xl font-bold">
        {current
          ? `Level ${current.number} of ${journey.levels.length}${
              levelColorName(current.color) ? ` · ${levelColorName(current.color)}` : ""
            }`
          : journey.pathway_complete ? "Pathway complete" : "Awaiting level placement"}
      </p>
      <ol className="mt-3 divide-y divide-rally-night-line" aria-label="Levels">
        {journey.levels.map((level) => {
          const swatch = levelSwatch(level.color);
          const isCurrent = level.level_id === current?.level_id;
          return (
            <li
              key={level.level_id}
              aria-current={isCurrent ? "step" : undefined}
              className="flex items-center gap-3 py-2"
            >
              <span
                aria-hidden="true"
                style={{ background: swatch.fill, color: swatch.on }}
                className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full font-bold"
              >
                {level.number}
              </span>
              <div>
                <p className="text-sm font-bold">
                  <span className="sr-only">Level {level.number}, </span>{level.name}
                  {isCurrent && <span className="font-normal"> · Current level</span>}
                </p>
                {level.required_total !== undefined && (
                  <p className="text-xs text-rally-bright">
                    {level.required_total === 0
                      ? "No required skills configured"
                      : `${level.required_passed}/${level.required_total} required skills passed`}
                    {!!level.optional_total && ` · ${level.optional_passed}/${level.optional_total} optional skills passed`}
                  </p>
                )}
              </div>
            </li>
          );
        })}
      </ol>
    </div>
  );
}

const RING_R = 36;
const RING_C = 2 * Math.PI * RING_R;

type CurrentLevel = NonNullable<Journey["current_level"]>;

function nextLevelStep(current: CurrentLevel): string {
  if (current.required_total === 0) return "No required skills configured";
  const remaining = current.skills_remaining;
  if (remaining === 0) {
    return current.required_total === undefined
      ? "Your coach reviews level placement."
      : "Required skills passed. Ready for level review.";
  }
  const skills = `${remaining} ${remaining === 1 ? "skill" : "skills"}`;
  return current.has_next_level
    ? `${skills} to Level ${current.number + 1}`
    : `${skills} to finish the pathway`;
}

export function LevelRing({ current }: { current: CurrentLevel }) {
  const done = current.required_passed ?? current.skills_done;
  const total = current.required_total ?? current.skills_total;
  const filled = total > 0 ? (done / total) * RING_C : 0;
  const swatch = levelSwatch(current.color);
  const colorName = levelColorName(current.color);

  return (
    <div className="overflow-hidden rounded-2xl bg-white border border-rally-line">
      <div
        data-testid="current-level-band"
        className="flex items-center justify-between gap-2 px-4 py-2.5 font-bold"
        style={{ background: swatch.fill, color: swatch.on }}
      >
        <span className="font-display text-base">
          {colorName ? `${colorName} level` : `Level ${current.number}`}
        </span>
        <span className="truncate text-[13px]">{current.name}</span>
      </div>
      <div className="flex items-center gap-4 p-4">
        <svg
          width="88"
          height="88"
          viewBox="0 0 88 88"
          role="img"
          aria-label={total > 0 ? `${done} of ${total} skills passed` : "No skills to count"}
          className="shrink-0"
        >
          <circle
            cx="44"
            cy="44"
            r={RING_R}
            fill="none"
            strokeWidth="10"
            className="stroke-rally-line"
          />
          <circle
            cx="44"
            cy="44"
            r={RING_R}
            fill="none"
            strokeWidth="10"
            strokeLinecap="round"
            strokeDasharray={`${filled} ${RING_C}`}
            transform="rotate(-90 44 44)"
            stroke={swatch.fill}
          />
          <text
            x="44"
            y="50"
            textAnchor="middle"
            className="fill-rally-ink font-display text-xl font-bold"
          >
            {total > 0 ? `${done}/${total}` : "—"}
          </text>
        </svg>
        <div className="min-w-0 space-y-1">
          <p className="font-display text-lg font-bold text-rally-ink">{current.name}</p>
          <p className="text-sm text-status-slate-700">{nextLevelStep(current)}</p>
          {current.pace_weeks !== null && (
            <p className="text-[13px] text-rally-muted">
              At this pace: about {current.pace_weeks} {current.pace_weeks === 1 ? "week" : "weeks"}
            </p>
          )}
        </div>
      </div>
    </div>
  );
}

const SKILL_STATE: Record<
  Journey["skills"][number]["state"],
  { label: string; mark: string; row: string; icon: string; tag: string }
> = {
  got_it: {
    label: "Got it",
    mark: "✓",
    row: "bg-white border-rally-line",
    icon: "bg-status-green-500 text-white",
    tag: "text-status-green-800",
  },
  working_on_it: {
    label: "Working on it",
    mark: "•",
    row: "bg-rally-cobalt-50 border-rally-cobalt-500",
    icon: "bg-rally-cobalt-600 text-white",
    tag: "text-rally-cobalt-700",
  },
  coming_up: {
    label: "Coming up",
    mark: "",
    row: "bg-white border-rally-line",
    icon: "bg-status-slate-100 border border-rally-bright",
    tag: "text-rally-muted",
  },
};

export function SkillChecklist({ skills }: { skills: Journey["skills"] }) {
  if (skills.length === 0) return null;
  return (
    <div className="space-y-2">
      <h2 className="font-display text-base font-bold text-rally-ink">Skills in this level</h2>
      <ul className="space-y-2">
        {skills.map((skill) => {
          const style = SKILL_STATE[skill.state];
          return (
            <li
              key={skill.skill_id}
              className={`flex items-center gap-2.5 rounded-xl border px-3 py-2.5 ${style.row}`}
            >
              <span
                aria-hidden="true"
                className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-[13px] font-bold ${style.icon}`}
              >
                {style.mark}
              </span>
              <span className="flex-1 min-w-0 truncate text-sm font-semibold text-rally-ink">
                {skill.name}
              </span>
              <span className={`shrink-0 text-xs font-bold ${style.tag}`}>{style.label}</span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

/** "10 skills mastered" / "1 level completed". */
export function milestoneLabel(m: { kind: string; count: number }): string {
  const noun =
    m.kind === "levels_completed"
      ? m.count === 1 ? "level completed" : "levels completed"
      : m.count === 1 ? "skill mastered" : "skills mastered";
  return `${m.count} ${noun}`;
}

/** Milestones the academy celebrates (Settings > Curriculum); nothing when off. */
export function MilestoneList({
  milestones,
  firstName,
}: {
  milestones: NonNullable<Journey["milestones"]>;
  firstName: string;
}) {
  if (milestones.length === 0) return null;
  // Newest first, like the wins below.
  const sorted = [...milestones].sort((a, b) => b.reached_at.localeCompare(a.reached_at));
  return (
    <div className="space-y-2" data-testid="parent-journey-milestones">
      <h2 className="font-display text-base font-bold text-rally-ink">Milestones</h2>
      <ul className="space-y-2">
        {sorted.map((m) => (
          <li
            key={`${m.kind}:${m.count}`}
            className="flex flex-col gap-1 rounded-[14px] border border-rally-volt-300 bg-rally-volt-100 px-3.5 py-3"
          >
            <p className="text-xs font-bold text-rally-volt-700">
              {formatWinDate(m.reached_at)} · Milestone
            </p>
            <p className="text-sm font-bold text-rally-ink">
              {firstName}: {milestoneLabel(m)}
            </p>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function RecentWins({ wins, studentId }: { wins: JourneyWin[]; studentId: string }) {
  if (wins.length === 0) return null;
  return (
    <div className="space-y-2">
      <h2 className="font-display text-base font-bold text-rally-ink">Recent wins</h2>
      <ul className="space-y-2">
        {wins.map((win) =>
          win.kind === "certificate" ? (
            <li
              key={`cert-${win.cert_id}`}
              className="flex flex-col gap-1 rounded-[14px] border border-rally-volt-300 bg-rally-volt-100 px-3.5 py-3"
            >
              <p className="text-xs font-bold text-rally-volt-700">
                {formatWinDate(win.at)} · Level complete
              </p>
              <p className="text-sm font-bold text-rally-ink">Certificate: {win.title}</p>
              {win.cert_id && (
                <Link
                  href={certificateHref(win.cert_id, studentId)}
                  className="text-[13px] font-bold text-rally-cobalt-700 underline-offset-2 hover:underline"
                >
                  View certificate
                </Link>
              )}
            </li>
          ) : (
            <li
              key={`skill-${win.title}-${win.at}`}
              className="flex flex-col gap-1 rounded-[14px] border border-rally-line bg-white px-3.5 py-3"
            >
              <p className="text-xs text-rally-muted">{formatWinDate(win.at)}</p>
              <p className="text-sm font-bold text-rally-ink">Mastered {win.title}</p>
              {win.coach_note && (
                <p className="mt-0.5 rounded-[10px] bg-status-slate-100 px-2.5 py-2 text-[13px] italic text-status-slate-700">
                  Coach: &ldquo;{win.coach_note}&rdquo;
                </p>
              )}
            </li>
          ),
        )}
      </ul>
    </div>
  );
}

export function PracticeDrillCard({ drill }: { drill: NonNullable<Journey["practice_drill"]> }) {
  return (
    <div className="flex flex-col gap-2 rounded-2xl p-4 bg-rally-cobalt-900 text-white">
      <h2 className="font-display text-base font-bold">
        Practise at home: {drill.skill_name ?? drill.title}
      </h2>
      <p className="text-[13px] text-rally-cobalt-100">
        A drill from your coach&apos;s lesson plan for the skill they&apos;re working on now.
      </p>
      <a
        href={drill.url}
        target="_blank"
        rel="noreferrer"
        className="inline-flex min-h-[44px] self-start items-center rounded-[10px] bg-rally-volt-400 px-3.5 text-[13px] font-bold text-rally-ink"
      >
        Watch drill<span className="sr-only"> (opens in a new tab)</span>
      </a>
    </div>
  );
}

export function CertificateList({ certs }: { certs: SkillCertificate[] }) {
  return (
    <div className="rounded-2xl overflow-hidden bg-white border border-rally-line">
      <h2 className="px-4 py-3 border-b border-rally-line text-sm font-bold text-rally-ink">
        Certificates
      </h2>
      <ul className="divide-y divide-rally-line">
        {certs.map((cert) => (
          <li key={cert.cert_id}>
            <Link
              href={certificateHref(cert.cert_id, cert.student_id)}
              className="flex items-center gap-3 px-4 py-3 hover:bg-rally-volt-100"
            >
              <span
                aria-hidden="true"
                className="h-8 w-8 rounded-lg flex items-center justify-center shrink-0 text-lg bg-rally-volt-100"
              >
                🏅
              </span>
              <div className="flex-1 min-w-0">
                <p className="text-sm font-semibold truncate text-rally-ink">{cert.level_name}</p>
                <p className="text-xs truncate text-rally-muted">{cert.program_name}</p>
              </div>
              <div className="shrink-0 text-right">
                <p className="text-xs font-medium text-rally-ink">
                  {new Date(cert.completed_at).toLocaleDateString(undefined, {
                    month: "short",
                    day: "numeric",
                    year: "numeric",
                  })}
                </p>
                <p className="text-[11px] text-rally-subtle">#{cert.cert_number}</p>
              </div>
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function JourneySkeleton() {
  return (
    <div className="space-y-4" aria-busy="true">
      <div className="h-36 animate-pulse rounded-2xl shimmer" />
      <div className="h-28 animate-pulse rounded-2xl shimmer" />
      {[0, 1, 2].map((i) => (
        <div key={i} className="h-11 animate-pulse rounded-xl shimmer" />
      ))}
    </div>
  );
}

/** "Tue" within the last week, "Oct 17" before that. */
export function formatWinDate(value: string, now: Date = new Date()): string {
  const at = new Date(value);
  const days = (now.getTime() - at.getTime()) / 86_400_000;
  if (days >= 0 && days < 6) {
    return at.toLocaleDateString(undefined, { weekday: "short" });
  }
  return at.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}
