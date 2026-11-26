"use client";

import { useQuery } from "@tanstack/react-query";

import { getAdminPathwayDashboard } from "@/lib/api/curriculum";
import { queryKeys } from "@/lib/query/keys";

/**
 * D-10 "Start at level": an enrolled child starts on the first level unless
 * the admin picks another. "" means the first level. Hidden when the academy
 * has no pathway (the backend then skips placement).
 */
export function StartLevelSelect({
  value,
  onChange,
  className,
}: {
  value: string;
  onChange: (levelId: string) => void;
  className?: string;
}) {
  const query = useQuery({
    queryKey: queryKeys.admin.pathwayDashboard(),
    queryFn: () => getAdminPathwayDashboard(),
    retry: false,
    staleTime: 5 * 60_000,
  });
  const levels = [...(query.data?.levels ?? [])].sort((a, b) => a.sequence - b.sequence);
  const [first, ...rest] = levels;
  if (!first) return null;
  return (
    <label className="grid gap-1 text-sm">
      Start at level
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className={className}
        data-testid="start-level-select"
      >
        <option value="">{first.name} (first level)</option>
        {rest.map((level) => (
          <option key={level.level_id} value={level.level_id}>
            {level.name}
          </option>
        ))}
      </select>
      <span className="text-xs text-rally-muted">
        A child who already has a level keeps it.
      </span>
    </label>
  );
}
