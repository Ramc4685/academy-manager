"use client";

import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { Button } from "@/components/ds/button";
import { Card } from "@/components/ds/card";
import { Chip } from "@/components/ds/chip";
import { RallyModal } from "@/components/ds/dialog-chrome";
import {
  confirmWaitlistOffer,
  declineWaitlistOffer,
  getParentAcademy,
  listParentWaitlist,
  type ParentWaitlistEntry,
} from "@/lib/api/parent";
import { formatAcademyDateTime } from "@/lib/format/academy-time";
import {
  classifyOfferError,
  formatCountdown,
  isUrgent,
  msUntil,
  offerFailureMessage,
  offerIsOpen,
  sortWaitlistEntries,
} from "@/lib/parent/waitlist-offers";
import { queryKeys } from "@/lib/query/keys";

/**
 * The landing spot for the "a seat opened" email (#828, X2).
 *
 * Renders nothing when the family has no waitlist rows, so the Requests page
 * looks exactly as before for everybody else. `highlightId` is the `?offer=`
 * from the email link: that card is scrolled to and outlined.
 */
export function WaitlistOffers({ highlightId }: { highlightId: string | null }) {
  const waitlistQuery = useQuery({
    queryKey: queryKeys.parent.waitlist(),
    queryFn: listParentWaitlist,
  });
  const academyQuery = useQuery({
    queryKey: queryKeys.parent.academy(),
    queryFn: getParentAcademy,
  });
  const now = useNow(30_000);
  // A confirmed or declined offer drops out of the refetched list (the
  // backend lists only open rows). Keep the answer on screen for this visit,
  // or the family would see "no longer open" right after a successful click.
  const [settled, setSettled] = useState<Record<string, Settled>>({});

  const live = waitlistQuery.data?.entries ?? [];
  const remembered = Object.values(settled)
    .filter((s) => !live.some((e) => e.waitlist_id === s.entry.waitlist_id))
    .map((s) => s.entry);
  const entries = sortWaitlistEntries([...live, ...remembered]);
  const timezone = academyQuery.data?.timezone ?? null;
  const highlightMissing =
    Boolean(highlightId) &&
    waitlistQuery.isSuccess &&
    !entries.some((e) => e.waitlist_id === highlightId);

  if (waitlistQuery.isError) {
    return (
      <Card p={16}>
        <p role="alert" className="text-sm text-status-red-800">
          We could not load your waitlist. Refresh the page to try again.
        </p>
      </Card>
    );
  }
  if (!waitlistQuery.isSuccess || (entries.length === 0 && !highlightId)) return null;

  return (
    <section data-testid="parent-waitlist-offers" aria-labelledby="waitlist-heading" className="space-y-3">
      <h2 id="waitlist-heading" className="text-sm font-bold text-rally-ink">
        Waitlist
      </h2>
      {highlightMissing && (
        <Card p={16}>
          <p data-testid="waitlist-offer-missing" className="text-sm text-rally-muted">
            That offer is no longer open. It may already have been confirmed or declined, or
            it closed more than two weeks ago.
          </p>
        </Card>
      )}
      {entries.map((entry) => (
        <WaitlistEntryCard
          key={entry.waitlist_id}
          entry={entry}
          now={now}
          timezone={timezone}
          highlighted={entry.waitlist_id === highlightId}
          outcome={settled[entry.waitlist_id]?.outcome ?? null}
          onSettled={(outcome) =>
            setSettled((prev) => ({ ...prev, [entry.waitlist_id]: { entry, outcome } }))
          }
        />
      ))}
    </section>
  );
}

type Outcome = "confirmed" | "declined";
type Settled = { entry: ParentWaitlistEntry; outcome: Outcome };

function WaitlistEntryCard({
  entry,
  now,
  timezone,
  highlighted,
  outcome,
  onSettled,
}: {
  entry: ParentWaitlistEntry;
  now: number;
  timezone: string | null;
  highlighted: boolean;
  outcome: Outcome | null;
  onSettled: (outcome: Outcome) => void;
}) {
  const queryClient = useQueryClient();
  const cardRef = useRef<HTMLDivElement>(null);
  const [declineOpen, setDeclineOpen] = useState(false);
  const confirmed = outcome === "confirmed";

  useEffect(() => {
    if (highlighted) cardRef.current?.scrollIntoView({ block: "center" });
  }, [highlighted]);

  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: queryKeys.parent.waitlist() });
    // A confirmed seat is a new enrollment: the children and schedule reads
    // must pick it up without a reload.
    void queryClient.invalidateQueries({ queryKey: queryKeys.parent.children() });
  };
  const confirmMutation = useMutation({
    mutationFn: () => confirmWaitlistOffer(entry.waitlist_id),
    onSuccess: () => {
      onSettled("confirmed");
      refresh();
    },
    // Expired or already-closed: the row's real state has moved on.
    onError: refresh,
  });
  const declineMutation = useMutation({
    mutationFn: () => declineWaitlistOffer(entry.waitlist_id),
    onSuccess: () => {
      setDeclineOpen(false);
      onSettled("declined");
      refresh();
    },
    onError: refresh,
  });

  const remaining = msUntil(entry.offer_expires_at, now);
  const open = offerIsOpen(entry, now);
  const failure = confirmMutation.error ?? declineMutation.error;
  const pending = confirmMutation.isPending || declineMutation.isPending;

  return (
    <div ref={cardRef}>
      <Card
        p={16}
        data-testid={`waitlist-entry-${entry.waitlist_id}`}
        className={highlighted ? "ring-2 ring-rally-cobalt-600" : undefined}
      >
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <p className="font-semibold text-rally-ink">{entry.session_title}</p>
            <p className="text-sm text-rally-muted">
              {entry.student_name}
              {entry.schedule_label ? ` · ${entry.schedule_label}` : ""}
            </p>
            {entry.location && <p className="text-xs text-rally-muted">{entry.location}</p>}
          </div>
          <StatusChip entry={entry} open={open && !outcome} outcome={outcome} />
        </div>

        {confirmed ? (
          <p role="status" data-testid="waitlist-offer-confirmed" className="mt-3 rounded-md bg-status-green-50 p-3 text-sm text-status-green-800">
            The seat is yours. {entry.student_name} is now enrolled in {entry.session_title}.
          </p>
        ) : outcome === "declined" ? (
          <p role="status" data-testid="waitlist-offer-declined" className="mt-3 text-sm text-rally-muted">
            You declined this seat. It has been released to the next family on the waitlist.
          </p>
        ) : open && !outcome ? (
          <div className="mt-3 space-y-3">
            <p className="text-sm text-rally-ink">
              A seat opened for {entry.student_name}. We are holding it until{" "}
              <strong>{formatAcademyDateTime(entry.offer_expires_at ?? "", timezone)}</strong>.
            </p>
            <p
              data-testid="waitlist-offer-countdown"
              aria-live="polite"
              className={`text-sm font-semibold ${
                isUrgent(remaining) ? "text-status-amber-800" : "text-rally-muted"
              }`}
            >
              {formatCountdown(remaining)}
            </p>
            <div className="flex flex-wrap gap-2">
              <Button
                size="md"
                onClick={() => confirmMutation.mutate()}
                disabled={pending}
                data-testid="waitlist-offer-confirm"
              >
                {confirmMutation.isPending ? "Confirming…" : "Confirm seat"}
              </Button>
              <Button
                size="md"
                variant="secondary"
                onClick={() => setDeclineOpen(true)}
                disabled={pending}
                data-testid="waitlist-offer-decline"
              >
                Decline
              </Button>
            </div>
          </div>
        ) : entry.status === "offered" || entry.status === "expired" ? (
          <p data-testid="waitlist-offer-expired" className="mt-3 text-sm text-rally-muted">
            {offerFailureMessage("expired")}
          </p>
        ) : (
          <p className="mt-3 text-sm text-rally-muted">
            {entry.student_name} is on the waitlist. We will email you as soon as a seat opens.
          </p>
        )}

        {failure && !declineOpen && (
          <p role="alert" data-testid="waitlist-offer-error" className="mt-3 rounded-md bg-status-red-50 p-3 text-sm text-status-red-800">
            {offerFailureMessage(classifyOfferError(failure))}
          </p>
        )}
      </Card>

      <RallyModal
        open={declineOpen}
        onOpenChange={(next) => {
          if (!pending) setDeclineOpen(next);
        }}
        overline="Waitlist offer"
        title="Decline this seat?"
        description=""
      >
        <div className="space-y-3 text-sm text-rally-muted">
          <p className="rounded-md border border-rally-line bg-rally-paper px-3 py-2 font-semibold text-rally-ink">
            {entry.student_name} · {entry.session_title}
          </p>
          <p>
            The seat goes to the next family on the waitlist straight away, and{" "}
            {entry.student_name} leaves the waitlist for this class. This cannot be undone.
          </p>
          {declineMutation.error && (
            <p role="alert" className="rounded-md bg-status-red-50 p-3 text-status-red-800">
              {offerFailureMessage(classifyOfferError(declineMutation.error))}
            </p>
          )}
          <div className="flex justify-end gap-2 pt-1">
            <Button variant="secondary" size="sm" onClick={() => setDeclineOpen(false)} disabled={pending}>
              Keep the offer
            </Button>
            <Button
              variant="danger"
              size="sm"
              onClick={() => declineMutation.mutate()}
              disabled={pending}
              data-testid="waitlist-offer-decline-confirm"
            >
              {declineMutation.isPending ? "Declining…" : "Decline seat"}
            </Button>
          </div>
        </div>
      </RallyModal>
    </div>
  );
}

function StatusChip({
  entry,
  open,
  outcome,
}: {
  entry: ParentWaitlistEntry;
  open: boolean;
  outcome: Outcome | null;
}) {
  if (outcome === "confirmed") return <Chip variant="enrolled" label="ENROLLED" />;
  if (outcome === "declined") return <Chip variant="expired" label="DECLINED" />;
  if (open) return <Chip variant="offered" label="SEAT OFFERED" />;
  if (entry.status === "waiting") return <Chip variant="waitlist" label="WAITING" />;
  return <Chip variant="expired" label="EXPIRED" />;
}

/** A clock that re-renders the countdown; coarse on purpose (see formatCountdown). */
function useNow(intervalMs: number): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), intervalMs);
    return () => window.clearInterval(id);
  }, [intervalMs]);
  return now;
}
