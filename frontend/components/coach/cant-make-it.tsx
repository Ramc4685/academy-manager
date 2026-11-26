"use client";

/**
 * S67 "I can't make it" (docs/design/coach-sick.md section 4): a coach tells
 * the academy they cannot teach a future class date. It only writes one
 * academy-inbox message; the class is not cancelled and families are not
 * told. Never queued offline: the coach is told to call instead.
 */

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import type { ApiError } from "@/lib/api/client";
import { getCoachAcademy, getCoachCoverRequest, requestCoachCover } from "@/lib/api/coach";
import { formatAcademyClock, formatInAcademyZone, parseAcademyInstant } from "@/lib/format/academy-time";
import { useOnline } from "@/lib/pwa/online";
import { queryKeys } from "@/lib/query/keys";
import { Button } from "@/components/ds/button";
import { DialogActions, DialogError, Field, RallyModal } from "@/components/ds/dialog-chrome";
import { useToast } from "@/components/ds/toast";

export function classDay(iso: string, timezone: string | null | undefined): string {
  return formatInAcademyZone(iso, timezone, { weekday: "short", month: "short", day: "numeric" });
}

export function CoverRequestedBlock({
  requestedAt,
  timezone,
  phone,
}: {
  requestedAt: string;
  timezone: string | null | undefined;
  phone: string | null | undefined;
}) {
  return (
    <div className="mt-2 rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-900" data-testid="coach-cover-requested">
      <p className="font-mono text-[10px] font-bold uppercase tracking-overline">● Cover requested</p>
      <p>
        You told the academy at {formatAcademyClock(requestedAt, timezone)}.
        {phone ? (
          <>
            {" "}If it is urgent, call <a className="underline" href={`tel:${phone}`}>{phone}</a>.
          </>
        ) : null}
      </p>
    </div>
  );
}

export function CantMakeIt({
  occurrenceId,
  title,
  startAt,
  status,
  timezone,
  now = new Date(),
}: {
  occurrenceId: string;
  title: string;
  startAt: string;
  status?: string;
  timezone: string | null | undefined;
  now?: Date;
}) {
  const online = useOnline();
  const [open, setOpen] = useState(false);
  const future = status !== "cancelled" && parseAcademyInstant(startAt).getTime() > now.getTime();
  const { data: academy } = useQuery({ queryKey: queryKeys.coach.academy(), queryFn: getCoachAcademy });
  const existing = useQuery({
    queryKey: queryKeys.coach.coverRequest(occurrenceId),
    queryFn: () => getCoachCoverRequest(occurrenceId),
    enabled: future && online,
    retry: false,
  });
  const phone = academy?.contact_phone;

  if (!future) return null;
  // Not assigned (a supervisor browsing another class): the server says 404.
  if ((existing.error as ApiError | null)?.status === 404) return null;
  if (existing.data?.requested_at) {
    return <CoverRequestedBlock requestedAt={existing.data.requested_at} timezone={timezone} phone={phone} />;
  }
  if (!online) {
    return (
      <p className="mt-2 text-sm text-rally-muted" data-testid="coach-cant-make-it-offline">
        I can&apos;t make it needs a connection.{phone ? <> Call <a className="underline" href={`tel:${phone}`}>{phone}</a>.</> : null}
      </p>
    );
  }

  const day = classDay(startAt, timezone);
  const academyName = academy?.name || "the academy";
  return (
    <>
      <button
        type="button"
        className="mt-2 inline-flex min-h-11 items-center text-sm font-semibold text-rally-cobalt underline"
        onClick={() => setOpen(true)}
        data-testid="coach-cant-make-it"
      >
        I can&apos;t make it
      </button>
      {open ? (
        <CantMakeItDialog
          occurrenceId={occurrenceId}
          title={`Can't make ${day}?`}
          description={`This tells ${academyName} you cannot teach ${title} at ${formatAcademyClock(startAt, timezone)}. The class is not cancelled and families are not told. The academy will arrange cover or cancel it.`}
          phone={phone}
          onClose={() => setOpen(false)}
        />
      ) : null}
    </>
  );
}

/** Mounted only while open, so the class page renders without a toast host. */
function CantMakeItDialog({
  occurrenceId,
  title,
  description,
  phone,
  onClose,
}: {
  occurrenceId: string;
  title: string;
  description: string;
  phone: string | null | undefined;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const { toast } = useToast();
  const [reason, setReason] = useState("");
  const send = useMutation({
    mutationFn: () => requestCoachCover(occurrenceId, reason),
    onSuccess: (data) => {
      queryClient.setQueryData(queryKeys.coach.coverRequest(occurrenceId), data);
      toast({ kind: "success", title: "The academy has been told." });
      onClose();
    },
  });
  return (
    <RallyModal open onOpenChange={(v) => !v && onClose()} overline="Class date" title={title} description={description}>
      {send.isError ? (
        <DialogError
          message={`We could not tell the academy. Check your connection${phone ? `, or call ${phone}` : ""}.`}
        />
      ) : null}
      <div className="my-3">
        <Field label="Reason (optional)">
          <input
            className="block w-full rounded-md border border-rally-line px-3 py-2 text-sm"
            value={reason}
            maxLength={200}
            placeholder="Unwell"
            onChange={(e) => setReason(e.target.value)}
          />
        </Field>
      </div>
      <DialogActions>
        <Button variant="secondary" style={{ minHeight: 50 }} autoFocus onClick={onClose}>
          Keep my class
        </Button>
        <Button
          style={{ minHeight: 50 }}
          disabled={send.isPending}
          onClick={() => send.mutate()}
          data-testid="coach-cant-make-it-send"
        >
          {send.isPending ? "Sending…" : "Tell the academy"}
        </Button>
      </DialogActions>
    </RallyModal>
  );
}
