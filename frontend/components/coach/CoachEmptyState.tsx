"use client";

import { useQuery } from "@tanstack/react-query";

import { getCoachAcademy, type CoachAcademy } from "@/lib/api/coach";
import { queryKeys } from "@/lib/query/keys";

/** "Questions? Call 555-0100 or email office@example.com", or null when the academy set neither. */
export function academyContactLine(academy: CoachAcademy | null | undefined): string | null {
  const phone = academy?.contact_phone?.trim();
  const email = academy?.contact_email?.trim();
  if (phone && email) return `Questions? Call ${phone} or email ${email}.`;
  if (phone) return `Questions? Call ${phone}.`;
  if (email) return `Questions? Email ${email}.`;
  return null;
}

/** The academy contact line; shares the coach layout's academy query. */
export function AcademyContact({ className }: { className?: string }) {
  const { data } = useQuery({ queryKey: queryKeys.coach.academy(), queryFn: getCoachAcademy });
  const line = academyContactLine(data);
  if (!line) return null;
  return (
    <p data-testid="academy-contact" className={className ?? "text-sm text-neutral-600 dark:text-neutral-300"}>
      {line}
    </p>
  );
}

/** A coach with no classes yet: say what happens next and who to ask. */
export function CoachEmptyState() {
  return (
    <div
      data-testid="coach-empty-state"
      className="rounded-lg border border-rally-line bg-white p-4 dark:bg-neutral-900"
    >
      <p className="font-medium">No classes yet</p>
      <p className="mt-1 text-sm text-neutral-600 dark:text-neutral-300">
        Classes appear here once the academy assigns them.
      </p>
      <AcademyContact className="mt-2 text-sm text-neutral-600 dark:text-neutral-300" />
    </div>
  );
}
