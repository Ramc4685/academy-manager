"use client";

import { useQuery } from "@tanstack/react-query";

import {
  listGlobalWaitlist,
  type AdminGlobalWaitlistSession,
  type AdminWaitlistEntry,
} from "@/lib/api/admin";
import { queryKeys } from "@/lib/query/keys";
import { Avatar } from "@/components/ds/avatar";
import { BigNum, Overline } from "@/components/ds/typography";
import { Card } from "@/components/ds/card";
import { Chip } from "@/components/ds/chip";
import { LaneHeader } from "@/components/ds/lane";

function formatDate(isoString: string): string {
  return new Date(isoString).toLocaleDateString([], { month: "short", day: "numeric" });
}

function formatTime(isoString: string): string {
  return new Date(isoString).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}

export default function AdminWaitlistPage() {
  const query = useQuery({
    queryKey: queryKeys.admin.globalWaitlist(),
    queryFn: listGlobalWaitlist,
  });
  const sessions = query.data?.sessions ?? [];
  const total = query.data?.total_waitlisted ?? 0;

  return (
    <section data-testid="admin-waitlist" className="space-y-6">
      <div className="grid gap-4 md:grid-cols-3">
        <Metric label="Total waitlisted" value={String(total)} />
        <Metric label="Sessions with queue" value={String(sessions.length)} />
        <Metric
          label="Largest queue"
          value={String(Math.max(0, ...sessions.map((session) => session.entries.length)))}
        />
      </div>

      <LaneHeader index="01" title="By session" />

      {query.isError ? (
        <Card p={20}>
          <p role="alert" className="text-sm text-red-700">Could not load waitlist.</p>
        </Card>
      ) : query.isLoading ? (
        <Skeleton />
      ) : sessions.length === 0 ? (
        <Card p={20}>
          <p className="text-sm text-rally-subtle" data-testid="admin-waitlist-empty">
            No waitlisted students.
          </p>
        </Card>
      ) : (
        <div className="space-y-4">
          {sessions.map((session) => (
            <SessionWaitlist key={session.session_id} session={session} />
          ))}
        </div>
      )}
    </section>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <Card p={20}>
      <Overline>{label}</Overline>
      <div className="mt-2">
        <BigNum size={28}>{value}</BigNum>
      </div>
    </Card>
  );
}

function SessionWaitlist({ session }: { session: AdminGlobalWaitlistSession }) {
  return (
    <Card p={0}>
      <div className="flex flex-col gap-4 border-b border-rally-line p-5 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <Overline>Session</Overline>
          <h2 className="mt-1 font-display text-[20px] font-semibold text-rally-ink">
            {session.title}
          </h2>
          <p className="mt-1 text-sm text-rally-muted">
            {session.location || "No location"} · {formatDate(session.start_at)} · {formatTime(session.start_at)}
          </p>
          <p className="mt-1 font-mono text-[10px] uppercase tracking-overline text-rally-subtle">
            {session.enrolled_count} / {session.capacity} enrolled · {session.waitlist_count} waiting
          </p>
        </div>
        <a
          href={`/admin/sessions/${session.session_id}`}
          className="inline-flex h-[30px] items-center justify-center rounded-lg bg-rally-cobalt px-3 font-body text-[12px] font-semibold text-white"
        >
          Manage session
        </a>
      </div>
      <div>
        {session.entries.map((entry, index) => (
          <WaitlistRow
            key={entry.waitlist_id}
            entry={entry}
            position={entry.position || index + 1}
          />
        ))}
      </div>
    </Card>
  );
}

function WaitlistRow({
  entry,
  position,
}: {
  entry: AdminWaitlistEntry;
  position: number;
}) {
  return (
    <div
      data-testid={`admin-waitlist-row-${entry.waitlist_id}`}
      className="grid gap-4 border-b border-rally-line p-5 last:border-0 md:grid-cols-[56px_1fr_180px_140px]"
    >
      <div className="flex h-11 w-11 items-center justify-center rounded-md bg-rally-paper font-display text-lg font-bold text-rally-ink">
        #{position}
      </div>
      <div className="flex min-w-0 items-center gap-3">
        <Avatar name={entry.full_name} size={34} />
        <div className="min-w-0">
          <div className="truncate font-semibold text-rally-ink">{entry.full_name}</div>
          <div className="font-mono text-[10px] text-rally-subtle">{entry.parent_id}</div>
        </div>
      </div>
      <div>
        <Overline>Joined queue</Overline>
        <div className="mt-1 font-mono text-[12px] font-semibold uppercase tracking-[0.05em] text-rally-ink">
          {formatDate(entry.added_at)}
        </div>
      </div>
      <div className="flex items-center md:justify-end">
        <Chip variant="waitlist" label={entry.status.toUpperCase()} />
      </div>
    </div>
  );
}

function Skeleton() {
  return (
    <div className="space-y-3">
      {[0, 1].map((i) => (
        <div key={i} className="h-32 animate-pulse rounded-lg bg-rally-paper" />
      ))}
    </div>
  );
}
