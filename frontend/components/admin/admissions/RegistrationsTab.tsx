"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";

import { listAdminRegistrations, type AdminRegistrationRow } from "@/lib/api/admin";
import { queryKeys } from "@/lib/query/keys";
import { Avatar, Card, Chip, Overline } from "@/components/ds";

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

function RegistrationsTable({ registrations }: { registrations: AdminRegistrationRow[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[860px] text-sm">
        <thead>
          <tr className="border-b border-neutral-200 bg-neutral-50 text-left">
            <th className="px-5 py-3 font-mono text-[10px] font-bold uppercase tracking-overline text-rally-muted">Student</th>
            <th className="px-3 py-3 font-mono text-[10px] font-bold uppercase tracking-overline text-rally-muted">Parent</th>
            <th className="px-3 py-3 font-mono text-[10px] font-bold uppercase tracking-overline text-rally-muted">Waiver</th>
            <th className="px-3 py-3 font-mono text-[10px] font-bold uppercase tracking-overline text-rally-muted">Updated</th>
            <th className="px-5 py-3 font-mono text-[10px] font-bold uppercase tracking-overline text-rally-muted">Review</th>
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
              <td className="px-5 py-4">
                <Link
                  href={`/admin/registrations/${encodeURIComponent(registration.application_id)}`}
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

function formatDate(value: string): string {
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "2-digit",
    year: "numeric",
  }).format(new Date(value));
}
