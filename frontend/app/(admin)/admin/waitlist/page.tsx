"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";

import { listAdminSessions } from "@/lib/api/admin";
import { queryKeys } from "@/lib/query/keys";

function todayISO(): string {
  return new Date().toISOString().slice(0, 10);
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
    <section data-testid="admin-waitlist">
      <header className="mb-5">
        <h1 className="font-display text-2xl font-semibold tracking-tight">Waitlist</h1>
        <p className="mt-1 text-sm text-slate-500">
          v2 waitlist actions are managed per session.
        </p>
      </header>

      {isLoading ? <p className="text-sm text-slate-500">Loading waitlist...</p> : null}
      {isError ? <p className="text-sm text-red-600">Could not load sessions.</p> : null}

      {!isLoading && !isError && waitlisted.length === 0 ? (
        <div className="rounded-lg border border-slate-200 bg-white p-4 text-sm text-slate-600 dark:border-slate-800 dark:bg-slate-950 dark:text-slate-400">
          No waitlisted students on today&apos;s sessions.
        </div>
      ) : null}

      <ul className="space-y-3">
        {waitlisted.map((session) => (
          <li key={session.session_id}>
            <Link
              href={`/admin/sessions/${session.session_id}` as Parameters<typeof Link>[0]["href"]}
              className="block rounded-lg border border-slate-200 bg-white p-4 hover:border-blue-300 dark:border-slate-800 dark:bg-slate-950"
            >
              <div className="flex items-center justify-between gap-3">
                <div>
                  <p className="font-semibold">{session.title}</p>
                  <p className="text-sm text-slate-500">{session.location}</p>
                </div>
                <span className="rounded-full bg-amber-100 px-2 py-1 text-xs font-semibold text-amber-800">
                  {session.waitlist_count} waiting
                </span>
              </div>
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}
