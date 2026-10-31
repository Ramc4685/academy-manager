import type { ParentProgressJourney } from "@/lib/api/parent";
import type { SkillCertificate } from "@/lib/api/curriculum";

// Presentational pieces of the parent progress journey (design: owner canvas
// "Parent · how far along"). Data shaping lives in the BFF; these only render.

type Journey = ParentProgressJourney;
type JourneyWin = Journey["recent_wins"][number];

export function LevelStrip({ firstName, journey }: { firstName: string; journey: Journey }) {
  const current = journey.current_level!;
  return (
    <div className="rounded-2xl px-4 pt-4 pb-3 bg-rally-ink text-white">
      <p className="text-xs font-bold uppercase tracking-chip text-rally-volt-300">
        {firstName}&apos;s badminton journey
      </p>
      <p className="font-display text-2xl font-bold">
        Level {current.number} of {journey.levels.length}
      </p>
      <ol className="mt-4 flex" aria-label="Levels">
        {journey.levels.map((level, idx) => {
          const isLast = idx === journey.levels.length - 1;
          const label =
            level.state === "done" ? "done" : level.state === "current" ? "current level" : "coming up";
          return (
            <li
              key={level.level_id}
              className="relative flex flex-1 min-w-0 flex-col items-center gap-1.5"
              aria-current={level.state === "current" ? "step" : undefined}
            >
              {!isLast && (
                <span
                  aria-hidden="true"
                  className={`absolute top-[15px] left-1/2 h-[3px] w-full ${
                    level.state === "done" ? "bg-status-green-500" : "bg-rally-night-line"
                  }`}
                />
              )}
              <span
                className={`relative z-10 flex items-center justify-center rounded-full font-display font-bold ${
                  level.state === "done"
                    ? "h-[26px] w-[26px] mt-[2px] text-xs bg-status-green-500 text-white"
                    : level.state === "current"
                      ? "h-[32px] w-[32px] -mt-[1px] text-sm bg-rally-volt-400 text-rally-ink ring-4 ring-rally-volt-400/30"
                      : "h-[26px] w-[26px] mt-[2px] text-xs bg-rally-night-line text-rally-subtle-ink border border-status-slate-700"
                }`}
              >
                {level.state === "done" ? "✓" : level.number}
                <span className="sr-only">
                  {`Level ${level.number}, ${level.name}: ${label}`}
                </span>
              </span>
              <span
                aria-hidden="true"
                className={`w-full truncate px-0.5 text-center text-[11px] ${
                  level.state === "current" ? "font-bold text-white" : "text-rally-bright"
                }`}
              >
                {level.name}
              </span>
            </li>
          );
        })}
      </ol>
    </div>
  );
}

const RING_R = 36;
const RING_C = 2 * Math.PI * RING_R;

export function LevelRing({ current }: { current: NonNullable<Journey["current_level"]> }) {
  const { skills_done: done, skills_total: total, skills_remaining: remaining } = current;
  const filled = total > 0 ? (done / total) * RING_C : 0;
  const nextStep =
    remaining === 0
      ? current.has_next_level
        ? `Level ${current.number} done, moving up to Level ${current.number + 1}`
        : "Every level done"
      : current.has_next_level
        ? `${remaining} ${remaining === 1 ? "skill" : "skills"} to Level ${current.number + 1}`
        : `${remaining} ${remaining === 1 ? "skill" : "skills"} to finish the pathway`;

  return (
    <div className="flex items-center gap-4 rounded-2xl p-4 bg-white border border-rally-line">
      <svg
        width="88"
        height="88"
        viewBox="0 0 88 88"
        role="img"
        aria-label={`${done} of ${total} skills done`}
        className="shrink-0"
      >
        <circle cx="44" cy="44" r={RING_R} fill="none" strokeWidth="10" className="stroke-rally-cobalt-100" />
        <circle
          cx="44"
          cy="44"
          r={RING_R}
          fill="none"
          strokeWidth="10"
          strokeLinecap="round"
          strokeDasharray={`${filled} ${RING_C}`}
          transform="rotate(-90 44 44)"
          className="stroke-rally-cobalt-600"
        />
        <text
          x="44"
          y="50"
          textAnchor="middle"
          className="fill-rally-ink font-display text-xl font-bold"
        >
          {done}/{total}
        </text>
      </svg>
      <div className="min-w-0 space-y-1">
        <p className="font-display text-lg font-bold text-rally-ink">{current.name}</p>
        <p className="text-sm text-status-slate-700">{nextStep}</p>
        {current.pace_weeks !== null && (
          <p className="text-[13px] text-rally-muted">
            At this pace: about {current.pace_weeks} {current.pace_weeks === 1 ? "week" : "weeks"}
          </p>
        )}
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

export function RecentWins({ wins }: { wins: JourneyWin[] }) {
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
              <a
                href={`#certificate-${win.cert_id}`}
                className="text-[13px] font-bold text-rally-cobalt-700 underline-offset-2 hover:underline"
              >
                View certificate
              </a>
            </li>
          ) : (
            <li
              key={`skill-${win.title}-${win.at}`}
              className="flex flex-col gap-1 rounded-[14px] border border-rally-line bg-white px-3.5 py-3"
            >
              <p className="text-xs text-rally-muted">{formatWinDate(win.at)}</p>
              <p className="text-sm font-bold text-rally-ink">Mastered {win.title}</p>
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
          <li
            key={cert.cert_id}
            id={`certificate-${cert.cert_id}`}
            className="flex items-center gap-3 px-4 py-3 scroll-mt-24 target:bg-rally-volt-100"
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
