"use client";

import Link from "next/link";
import type { Route } from "next";
import { useQuery } from "@tanstack/react-query";

import { listAdminRegistrations, type AdminRegistrationRow } from "@/lib/api/admin";
import { queryKeys } from "@/lib/query/keys";
import { Avatar, Card, Chip, Overline, PhoneList, PhoneListRow } from "@/components/ds";
import { useIsPhone } from "@/lib/use-is-phone";
import { actionCellClass, actionHeaderClass } from "@/lib/sticky-action-column";

export function RegistrationsTab() {
  const query = useQuery({
    queryKey: queryKeys.admin.registrations(),
    queryFn: () => listAdminRegistrations(),
    retry: false,
  });

  return (
    <div data-testid="admin-registrations-tab" className="space-y-4">
      <Card p={0}>
        {query.isPending ? (
          <p className="p-5 text-sm text-rally-subtle">Loading registrations...</p>
        ) : query.isError ? (
          <p role="alert" className="p-5 text-sm text-red-700">Could not load registrations.</p>
        ) : query.data.registrations.length === 0 ? (
          <p className="p-5 text-sm text-rally-subtle" data-testid="admin-registrations-empty">
            No registrations need approval.
          </p>
        ) : (
          <RegistrationsTable registrations={query.data.registrations} />
        )}
      </Card>
    </div>
  );
}

function reviewHref(registration: AdminRegistrationRow): Route {
  return `/admin/registrations/${encodeURIComponent(registration.application_id)}` as Route;
}

/**
 * #857: on a phone the Review link was the fifth column of a 860px table, so
 * the one action this queue exists for sat off-screen. One layout at a time —
 * see `lib/use-is-phone.ts`.
 */
function RegistrationsTable({ registrations }: { registrations: AdminRegistrationRow[] }) {
  const isPhone = useIsPhone();
  if (isPhone) {
    return (
      <PhoneList aria-label="Registrations" data-testid="admin-registrations-phone-list">
        {registrations.map((registration) => (
          <RegistrationPhoneRow key={registration.application_id} registration={registration} />
        ))}
      </PhoneList>
    );
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[860px] text-sm">
        <thead>
          <tr className="border-b border-neutral-200 bg-neutral-50 text-left">
            <th className="px-5 py-3 font-mono text-[10px] font-bold uppercase tracking-overline text-rally-muted">Student</th>
            <th className="px-3 py-3 font-mono text-[10px] font-bold uppercase tracking-overline text-rally-muted">Parent</th>
            <th className="px-3 py-3 font-mono text-[10px] font-bold uppercase tracking-overline text-rally-muted">Waiver</th>
            <th className="px-3 py-3 font-mono text-[10px] font-bold uppercase tracking-overline text-rally-muted">Updated</th>
            <th className={`px-5 py-3 font-mono text-[10px] font-bold uppercase tracking-overline text-rally-muted ${actionHeaderClass}`}>Review</th>
          </tr>
        </thead>
        <tbody>
          {registrations.map((registration) => (
            <tr
              key={registration.application_id}
              data-testid={`admin-registration-row-${registration.application_id}`}
              className="border-b border-neutral-100 last:border-0"
            >
              <td className="px-5 py-4">
                <div className="flex items-center gap-3">
                  <Avatar name={registration.student_name ?? "Student"} size={34} />
                  <div>
                    <div className="font-semibold text-rally-base">{registration.student_name || "Unnamed student"}</div>
                    <Overline>{registration.status.replaceAll("_", " ")}</Overline>
                    {registration.zero_quote_period && (
                      <div className="mt-1" data-testid={`admin-registration-no-payment-${registration.application_id}`}>
                        <Chip variant="nocharge" label="NO PAYMENT" />
                      </div>
                    )}
                    {/* Issue #776: evidence, not intent — the stamp is only
                        written when a waitlist/decline email actually went, so
                        an un-chipped decided row still needs a phone call. */}
                    {registration.family_notified_at && (
                      <div className="mt-1" data-testid={`admin-registration-family-notified-${registration.application_id}`}>
                        <Chip variant="approved" label="FAMILY NOTIFIED" />
                      </div>
                    )}
                  </div>
                </div>
              </td>
              <td className="px-3 py-4">
                <div className="font-semibold text-rally-base">{registration.parent_name || "Parent"}</div>
                <div className="text-[12px] text-rally-subtle">{registration.parent_email}</div>
              </td>
              <td className="px-3 py-4">
                <Chip
                  variant={registration.waiver_satisfied ? "approved" : "pending"}
                  label={registration.waiver_required ? (registration.waiver_satisfied ? "SIGNED" : "NEEDED") : "NOT REQUIRED"}
                />
              </td>
              <td className="px-3 py-4 font-mono text-[11px] text-rally-muted">{formatDate(registration.updated_at)}</td>
              <td className={`${actionCellClass} bg-white`}>
                <Link
                  href={reviewHref(registration)}
                  className="inline-flex min-h-touch items-center rounded-md bg-rally-ink px-3 py-2 text-sm font-semibold text-white"
                >
                  Review
                </Link>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/**
 * The waiver chip is line 1's primary slot: it is the single fact that decides
 * whether this application can be approved today. Same chip the table renders
 * — the phone row is a second layout, never a second derivation.
 */
function RegistrationPhoneRow({ registration }: { registration: AdminRegistrationRow }) {
  const href = reviewHref(registration);
  const name = registration.student_name || "Unnamed student";
  return (
    <PhoneListRow
      data-testid={`admin-registration-row-${registration.application_id}`}
      leading={<Avatar name={registration.student_name ?? "Student"} size={34} />}
      title={name}
      href={href}
      titleTestId={`admin-registration-link-${registration.application_id}`}
      primary={
        <Chip
          variant={registration.waiver_satisfied ? "approved" : "pending"}
          label={
            registration.waiver_required
              ? registration.waiver_satisfied
                ? "SIGNED"
                : "NEEDED"
              : "NOT REQUIRED"
          }
        />
      }
      actionsLabel={`Actions for ${name}`}
      actionsTestId={`admin-registration-actions-${registration.application_id}`}
      actions={[{ key: "review", label: "Review", href }]}
      secondary={
        <>
          <Overline>{registration.status.replaceAll("_", " ")}</Overline>
          <div className="flex flex-wrap items-center gap-2">
            {registration.zero_quote_period && (
              <span data-testid={`admin-registration-no-payment-${registration.application_id}`}>
                <Chip variant="nocharge" label="NO PAYMENT" />
              </span>
            )}
            {registration.family_notified_at && (
              <span
                data-testid={`admin-registration-family-notified-${registration.application_id}`}
              >
                <Chip variant="approved" label="FAMILY NOTIFIED" />
              </span>
            )}
          </div>
          <div className="break-words">
            {registration.parent_name || "Parent"} · {registration.parent_email}
          </div>
          <div className="font-mono text-[11px]">
            Updated {formatDate(registration.updated_at)}
          </div>
        </>
      }
    />
  );
}

function formatDate(value: string): string {
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "2-digit",
    year: "numeric",
  }).format(new Date(value));
}
