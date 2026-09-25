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
import { PhoneList, PhoneListRow } from "@/components/ds/phone-row";
import { useIsPhone } from "@/lib/use-is-phone";
import { offerExpiryLabel } from "@/lib/admin/waitlist-offer";

function formatDate(isoString: string): string {
  return new Date(isoString).toLocaleDateString([], { month: "short", day: "numeric" });
}

function formatTime(isoString: string): string {
  return new Date(isoString).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}

/**
 * #860: the row used to print `entry.parent_id` — a Mongo object id an admin
 * can do nothing with. The read now joins the parent's display name; "Not on
 * file" is the honest answer when that join comes back empty, which is still
 * more use than an id nobody can look up.
 */
function parentLabel(entry: AdminWaitlistEntry): string {
  return entry.parent_name?.trim() || "Not on file";
}

export function WaitlistTab() {
  const query = useQuery({
    queryKey: queryKeys.admin.globalWaitlist(),
    queryFn: listGlobalWaitlist,
  });
  const sessions = query.data?.sessions ?? [];
  const total = query.data?.total_waitlisted ?? 0;
  const offered = query.data?.total_offered ?? 0;

  return (
    <div data-testid="admin-waitlist-tab" className="space-y-6">
      <div className="grid gap-4 md:grid-cols-3">
        <Metric label="Total waitlisted" value={String(total)} />
        {/* X2: a held seat is invisible in "enrolled" and in the queue alike. */}
        <Metric label="Seats offered" value={String(offered)} />
        <Metric label="Sessions with queue" value={String(sessions.length)} />
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
    </div>
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
            {session.offered_count ? ` · ${session.offered_count} seat offered` : ""}
          </p>
        </div>
        <a
          href={`/admin/sessions/${session.session_id}`}
          className="inline-flex min-h-touch items-center justify-center rounded-lg bg-rally-cobalt px-3 font-body text-[12px] font-semibold text-white"
        >
          Manage session
        </a>
      </div>
      <WaitlistEntries entries={session.entries} />
    </Card>
  );
}

/**
 * #857: the four-column grid already stacked on a phone, but it stacked into a
 * 56px number block, a name, an "Joined queue" label and a chip — four
 * full-width blocks per waiting student, so one screen held two people. The
 * shared phone row says the same thing in two lines.
 */
function WaitlistEntries({ entries }: { entries: AdminWaitlistEntry[] }) {
  const isPhone = useIsPhone();
  if (isPhone) {
    return (
      <PhoneList aria-label="Waitlist" data-testid="admin-waitlist-phone-list">
        {entries.map((entry, index) => {
          const position = entry.position || index + 1;
          const offer = entry.status === "offered";
          return (
            <PhoneListRow
              key={entry.waitlist_id}
              data-testid={`admin-waitlist-row-${entry.waitlist_id}`}
              leading={
                <span className="flex size-9 items-center justify-center rounded-md bg-rally-paper font-display text-sm font-bold text-rally-ink">
                  {offer ? "—" : `#${position}`}
                </span>
              }
              title={entry.full_name}
              primary={<EntryChip entry={entry} />}
              secondary={
                <>
                  {offer ? (
                    <div>{offerExpiryLabel(entry.offer_expires_at)}</div>
                  ) : (
                    <div>Joined {formatDate(entry.added_at)}</div>
                  )}
                  <div>Parent: {parentLabel(entry)}</div>
                </>
              }
            />
          );
        })}
      </PhoneList>
    );
  }
  return (
    <div>
      {entries.map((entry, index) => (
        <WaitlistRow
          key={entry.waitlist_id}
          entry={entry}
          position={entry.position || index + 1}
        />
      ))}
    </div>
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
        {entry.status === "offered" ? "—" : `#${position}`}
      </div>
      <div className="flex min-w-0 items-center gap-3">
        <Avatar name={entry.full_name} size={34} />
        <div className="min-w-0">
          <div className="truncate font-semibold text-rally-ink">{entry.full_name}</div>
          <div className="truncate text-[12px] text-rally-subtle">
            Parent: {parentLabel(entry)}
          </div>
        </div>
      </div>
      {entry.status === "offered" ? (
        <div data-testid={`admin-waitlist-offer-expiry-${entry.waitlist_id}`}>
          <Overline>Offer</Overline>
          <div className="mt-1 text-[12px] font-semibold text-rally-ink">
            {offerExpiryLabel(entry.offer_expires_at) ?? "Held"}
          </div>
        </div>
      ) : (
        <div>
          <Overline>Joined queue</Overline>
          <div className="mt-1 font-mono text-[12px] font-semibold uppercase tracking-[0.05em] text-rally-ink">
            {formatDate(entry.added_at)}
          </div>
        </div>
      )}
      <div className="flex items-center md:justify-end">
        <EntryChip entry={entry} />
      </div>
    </div>
  );
}

function EntryChip({ entry }: { entry: AdminWaitlistEntry }) {
  return entry.status === "offered" ? (
    <Chip variant="offered" label="SEAT OFFERED" />
  ) : (
    <Chip variant="waitlist" label={entry.status.toUpperCase()} />
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
