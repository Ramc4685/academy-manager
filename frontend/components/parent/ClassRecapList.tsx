"use client";

import { useQuery } from "@tanstack/react-query";

import {
  listChildClassRecaps,
  type ChildClassRecap,
  type ChildRecapSkill,
} from "@/lib/api/class-recap";
import { getParentAcademy } from "@/lib/api/parent";
import { parseAcademyInstant, resolveAcademyTimeZone } from "@/lib/format/academy-time";
import { queryKeys } from "@/lib/query/keys";

function SkillLine({ skills }: { skills: ChildRecapSkill[] }) {
  return (
    <>
      {skills.map((s, i) => (
        <span key={s.skill_id}>{`${i > 0 ? ", " : ""}${s.name}${s.passed ? " ✓" : ""}`}</span>
      ))}
    </>
  );
}

export function ClassRecapItems({
  recaps,
  firstName,
  timeZone,
}: {
  recaps: ChildClassRecap[];
  firstName: string;
  timeZone: string | null;
}) {
  const zone = resolveAcademyTimeZone(timeZone).timeZone;
  return (
    <div className="rounded-2xl border border-rally-line bg-white p-4" data-testid="parent-class-recaps">
      <p className="text-sm font-bold text-rally-ink">{`What ${firstName} did in class`}</p>
      <ul className="mt-2 divide-y divide-rally-line">
        {recaps.map((r) => {
          return (
            <li key={r.occurrence_id} className="py-2 text-sm">
              <p className="text-xs text-rally-muted">
                {parseAcademyInstant(r.class_starts_at).toLocaleDateString("en-US", {
                  weekday: "short",
                  month: "short",
                  day: "numeric",
                  timeZone: zone,
                })}
              </p>
              <p className="text-rally-ink">
                Class worked on: <SkillLine skills={r.taught_skills} />
              </p>
              <p className="text-rally-ink">
                {r.practiced_skills.length > 0 ? (
                  <>
                    {`${firstName} practised: `}
                    <SkillLine skills={r.practiced_skills} />
                  </>
                ) : (
                  <span className="text-rally-muted">
                    {`The coach did not record which skills ${firstName} practised.`}
                  </span>
                )}
              </p>
            </li>
          );
        })}
      </ul>
      {recaps.some((r) => [...r.taught_skills, ...r.practiced_skills].some((s) => s.passed)) && (
        <p className="mt-2 text-xs text-rally-muted" data-testid="parent-class-recaps-pass-note">
          {`✓ means ${firstName} has passed that skill as of today. It may have been passed at a later class, not the one shown.`}
        </p>
      )}
    </div>
  );
}

/** The parent's own child only: no report text, no other children. */
export function ClassRecapList({ studentId, firstName }: { studentId: string; firstName: string }) {
  const { data } = useQuery({
    queryKey: queryKeys.parent.classRecaps(studentId),
    queryFn: () => listChildClassRecaps(studentId),
  });
  const { data: academy } = useQuery({
    queryKey: queryKeys.parent.academy(),
    queryFn: getParentAcademy,
  });
  if (!data || data.recaps.length === 0) return null;
  return (
    <ClassRecapItems
      recaps={data.recaps}
      firstName={firstName}
      timeZone={academy?.timezone ?? null}
    />
  );
}
