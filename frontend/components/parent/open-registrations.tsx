"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { UserPlus } from "lucide-react";

import { listParentRegistrations, type ParentRegistration } from "@/lib/api/parent";
import { queryKeys } from "@/lib/query/keys";

/** S02: what each registration state means to the family, in plain words. */
export function registrationStateCopy(row: ParentRegistration): {
  label: string;
  detail: string;
} {
  switch (row.state) {
    case "finish":
      return {
        label: "Finish registration",
        detail: "This registration is not finished yet. Pick up where you left off.",
      };
    case "waiting":
      return {
        label: "Waiting for the academy to confirm",
        detail: "We will email you when the academy confirms.",
      };
    case "waitlisted":
      return {
        label: "On the waitlist",
        detail: "We will email you if a seat opens.",
      };
    default:
      return {
        label: "Not accepted",
        detail: "The academy could not offer a place. Check your email for details.",
      };
  }
}

export function useParentRegistrations() {
  return useQuery({
    queryKey: queryKeys.parent.registrations(),
    queryFn: listParentRegistrations,
  });
}

/** Link into the wizard: "Add a child or enroll in a class". */
export function AddChildLink({ className = "" }: { className?: string }) {
  return (
    <Link
      href="/parent/onboarding"
      data-testid="parent-add-child"
      className={`inline-flex min-h-touch items-center gap-2 rounded-xl border border-rally-line bg-white px-4 text-sm font-bold text-rally-cobalt-700 transition-all duration-200 active:scale-95 ${className}`}
    >
      <UserPlus size={16} aria-hidden="true" />
      Add a child or enroll in a class
    </Link>
  );
}

/**
 * One card listing every registration that is not finished or not yet
 * confirmed, so a child never disappears between the wizard and the roster.
 * Renders nothing when there are none (or the read fails: the page around it
 * still works).
 */
export function OpenRegistrationsCard({ rows }: { rows: ParentRegistration[] }) {
  if (rows.length === 0) return null;
  return (
    <section
      data-testid="parent-open-registrations"
      aria-labelledby="parent-open-registrations-title"
      className="rounded-2xl border border-rally-line bg-white p-4 animate-fade-in-up"
    >
      <h2
        id="parent-open-registrations-title"
        className="font-display text-base font-bold text-rally-ink"
      >
        Registrations in progress
      </h2>
      <ul className="mt-2 divide-y divide-rally-line">
        {rows.map((row) => {
          const copy = registrationStateCopy(row);
          const what = [row.session_title, row.schedule_label].filter(Boolean).join(" · ");
          return (
            <li
              key={row.application_id}
              data-testid={`parent-registration-${row.application_id}`}
              className="flex flex-wrap items-center justify-between gap-2 py-3"
            >
              <div className="min-w-0">
                <p className="text-sm font-bold text-rally-ink">
                  {row.child_first_name}
                  {what && <span className="font-normal text-rally-muted"> · {what}</span>}
                </p>
                <p className="text-xs text-rally-muted">
                  {row.state === "finish" ? copy.detail : `${copy.label}. ${copy.detail}`}
                </p>
              </div>
              {row.state === "finish" && (
                <Link
                  href={`/parent/onboarding?application=${encodeURIComponent(row.application_id)}`}
                  className="inline-flex min-h-touch items-center rounded-xl bg-rally-cobalt-600 px-4 text-sm font-bold text-white hover:bg-rally-cobalt-700"
                >
                  {copy.label}
                </Link>
              )}
            </li>
          );
        })}
      </ul>
    </section>
  );
}
