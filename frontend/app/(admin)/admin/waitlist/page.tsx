"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";

import { listAdminSessions, type AdminSessionView } from "@/lib/api/admin";
import { queryKeys } from "@/lib/query/keys";
import { Card } from "@/components/ds/card";
import { Chip } from "@/components/ds/chip";

function todayISO(): string {
  return new Date().toISOString().slice(0, 10);
}

function formatTime(isoString: string): string {
  return new Date(isoString).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}

export default function AdminWaitlistPage() {
  const date = todayISO();
  const { data, isLoading, isError } = useQuery({
    queryKey: queryKeys.admin.sessions(date),
    queryFn: () => listAdminSessions(date),
  });

  const sessions = data?.sessions ?? [];
  const waitlisted = sessions.filter((session) => session.waitlist_count > 0);

  return (
    <section data-testid="admin-waitlist" className="space-y-6">
      {isLoading ? <p className="text-sm text-rally-subtle">Loading waitlist...</p> : null}
      {isError ? <p className="text-sm text-red-600">Could not load sessions.</p> : null}

      {!isLoading && !isError && waitlisted.length === 0 ? (
        <p className="text-sm text-rally-subtle" data-testid="admin-waitlist-empty">
          No waitlisted students on today&apos;s sessions.
        </p>
      ) : null}

      {waitlisted.length > 0 && (
        <Card p={20}>
          <WaitlistTable sessions={waitlisted} />
        </Card>
      )}
    </section>
  );
}

function WaitlistTable({ sessions }: { sessions: AdminSessionView[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-neutral-200 text-left dark:border-neutral-800">
            <th className="px-2 pb-3 font-mono text-[10px] font-bold uppercase tracking-overline text-rally-muted">Session</th>
            <th className="px-2 pb-3 font-mono text-[10px] font-bold uppercase tracking-overline text-rally-muted">Location</th>
            <th className="px-2 pb-3 font-mono text-[10px] font-bold uppercase tracking-overline text-rally-muted text-right">Time</th>
            <th className="px-2 pb-3 font-mono text-[10px] font-bold uppercase tracking-overline text-rally-muted text-right">Waitlist</th>
            <th className="px-2 pb-3 font-mono text-[10px] font-bold uppercase tracking-overline text-rally-muted text-right">Action</th>
          </tr>
        </thead>
        <tbody>
          {sessions.map((session) => (
            <tr key={session.session_id} data-testid={`admin-waitlist-row-${session.session_id}`} className="border-b border-neutral-100 last:border-0 dark:border-neutral-800">
              <td className="px-2 py-3 font-medium text-rally-base">{session.title}</td>
              <td className="px-2 py-3 text-rally-subtle">{session.location}</td>
              <td className="px-2 py-3 text-right text-rally-subtle">
                {formatTime(session.start_at)}
              </td>
              <td className="px-2 py-3 text-right">
                <Chip variant="waitlist" label={`${session.waitlist_count} WAITING`} />
              </td>
              <td className="px-2 py-3 text-right">
                <Link
                  href={`/admin/sessions/${session.session_id}` as Parameters<typeof Link>[0]["href"]}
                  className="font-medium text-blue-600 hover:text-blue-800 dark:text-blue-400 dark:hover:text-blue-300"
                >
                  Manage
                </Link>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
