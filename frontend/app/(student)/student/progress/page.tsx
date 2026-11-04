"use client";

import { useQuery } from "@tanstack/react-query";

import { getMyProgress } from "@/lib/api/student";
import { queryKeys } from "@/lib/query/keys";
import type { SkillPassportEntry } from "@/lib/api/curriculum";
import { SkillStatusChip, skillStatusToneClasses } from "@/components/skills/SkillStatusChip";

export default function StudentProgressPage() {
  const { data, isLoading, isError } = useQuery({
    queryKey: queryKeys.student.progress(),
    queryFn: getMyProgress,
  });

  const skills = data?.passport ?? [];
  const passedCount = skills.filter((s) => s.status === "PASSED").length;

  return (
    <section data-testid="student-progress">
      <div className="mb-4 animate-fade-in-up">
        <h1 className="font-display text-2xl font-bold tracking-tight text-rally-ink">Progress</h1>
        <p className="text-sm mt-0.5 text-rally-muted">Your skill passport</p>
      </div>

      {isError ? (
        <p className="text-sm text-status-red-600">Could not load your progress.</p>
      ) : isLoading ? (
        <div className="space-y-2">
          {[0, 1, 2, 3].map((i) => (
            <div key={i} className="h-11 animate-pulse rounded-xl shimmer" />
          ))}
        </div>
      ) : skills.length === 0 ? (
        <div className="rounded-2xl p-10 bg-white border border-rally-line">
          <p className="text-sm text-rally-muted">No skills found for this program yet.</p>
        </div>
      ) : (
        <>
          <div className="rounded-2xl p-4 bg-white border border-rally-line mb-4">
            <div className="flex items-center justify-between mb-3">
              <p className="text-sm font-bold text-rally-ink">
                {passedCount}/{skills.length} passed
              </p>
              <span className="text-xs font-semibold px-2 py-0.5 rounded-full bg-rally-cobalt-50 text-rally-cobalt-600">
                {skills.length > 0 ? Math.round((passedCount / skills.length) * 100) : 0}%
              </span>
            </div>
            <div className="h-2 rounded-full overflow-hidden bg-rally-line">
              <div
                className="h-full rounded-full bg-rally-cobalt-600 transition-all duration-500"
                style={{ width: `${skills.length > 0 ? Math.round((passedCount / skills.length) * 100) : 0}%` }}
              />
            </div>
          </div>
          <ul className="space-y-2 stagger-children">
            {skills.map((entry) => (
              <SkillItem key={entry.skill_id} entry={entry} />
            ))}
          </ul>
        </>
      )}
    </section>
  );
}

function SkillItem({ entry }: { entry: SkillPassportEntry }) {
  const checkmark = entry.status === "PASSED";
  const classes = skillStatusToneClasses(entry.status);

  return (
    <li className="flex items-center gap-3 rounded-xl px-3 py-2.5 bg-white border border-rally-line animate-fade-in-up">
      <div className={`h-7 w-7 rounded-lg flex items-center justify-center shrink-0 text-sm ${classes}`}>
        {checkmark ? "✓" : entry.sequence}
      </div>
      <div className="flex-1 min-w-0">
        <p className="text-sm font-medium truncate text-rally-ink">{entry.skill_name}</p>
      </div>
      <SkillStatusChip status={entry.status} />
    </li>
  );
}
