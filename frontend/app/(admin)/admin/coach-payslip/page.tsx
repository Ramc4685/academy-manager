"use client";

import { useQuery } from "@tanstack/react-query";

import { listAdminSessions, listAdminUsers } from "@/lib/api/admin";

function money(cents: number): string {
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(cents / 100);
}

export default function AdminCoachPayslipPage() {
  const coachesQuery = useQuery({
    queryKey: ["admin", "users", "coach"],
    queryFn: () => listAdminUsers("coach"),
  });
  const sessionsQuery = useQuery({
    queryKey: ["admin", "sessions", "today", "payslip"],
    queryFn: () => listAdminSessions(),
  });

  const coaches = coachesQuery.data?.users ?? [];
  const sessions = sessionsQuery.data?.sessions ?? [];
  const rows = coaches.map((coach) => {
    const assigned = sessions.filter((session) => session.coach_id === coach.user_id);
    const students = assigned.reduce((sum, session) => sum + session.enrolled_count, 0);
    return {
      coach,
      sessions: assigned.length,
      students,
      expectedCutCents: students * 2800,
    };
  });

  const loading = coachesQuery.isLoading || sessionsQuery.isLoading;
  const error = coachesQuery.isError || sessionsQuery.isError;

  return (
    <section data-testid="admin-coach-payslip" className="space-y-5">
      <div>
        <h1 className="text-2xl font-semibold">Coach payslip</h1>
        <p className="mt-1 text-sm text-neutral-500">
          Today&apos;s coach payout preview from assigned sessions and active roster counts.
        </p>
      </div>

      {error ? (
        <p role="alert" className="rounded-md bg-red-50 p-3 text-sm text-red-700">
          Could not load coach payslip data.
        </p>
      ) : loading ? (
        <Skeleton />
      ) : rows.length === 0 ? (
        <p className="text-sm text-neutral-500">No coaches found.</p>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-neutral-200 bg-white dark:border-neutral-800 dark:bg-neutral-900">
          <table className="w-full min-w-[720px] text-sm">
            <thead>
              <tr className="border-b border-neutral-200 text-left text-neutral-500 dark:border-neutral-800">
                <th className="px-4 py-3 font-medium">Coach</th>
                <th className="px-4 py-3 font-medium text-right">Sessions</th>
                <th className="px-4 py-3 font-medium text-right">Students</th>
                <th className="px-4 py-3 font-medium text-right">Expected cut</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.coach.user_id} className="border-b border-neutral-100 last:border-0 dark:border-neutral-800">
                  <td className="px-4 py-3">
                    <div className="font-medium">{row.coach.display_name || row.coach.email}</div>
                    <div className="font-mono text-xs text-neutral-500">{row.coach.user_id}</div>
                  </td>
                  <td className="px-4 py-3 text-right tabular-nums">{row.sessions}</td>
                  <td className="px-4 py-3 text-right tabular-nums">{row.students}</td>
                  <td className="px-4 py-3 text-right font-medium tabular-nums">
                    {money(row.expectedCutCents)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function Skeleton() {
  return (
    <div className="space-y-2">
      {[0, 1, 2].map((i) => (
        <div key={i} className="h-14 animate-pulse rounded-lg bg-neutral-100 dark:bg-neutral-800" />
      ))}
    </div>
  );
}
