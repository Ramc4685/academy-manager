"use client";

import { useState } from "react";
import { useMutation } from "@tanstack/react-query";

import { holdEnrollment, returnFromHold } from "@/lib/api/admin";

import { Button } from "@/components/ds/button";
import { DialogActions, DialogError, Field, RallyModal as RallyDialog } from "@/components/ds/dialog-chrome";

// `inputClass` and the date helper live in the sessions route's format.ts; a
// components/ file must not import from an app/ route, so they are duplicated
// here the same way notify-panel.tsx duplicates its own `dateInputValue`.
const inputClass =
  "w-full rounded-md border border-rally-line bg-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-rally-cobalt-600/30";

/** Local-zone yyyy-mm-dd; `toISOString()` would slide the date west of UTC. */
function dateInputValueFromOffset(days: number): string {
  const value = new Date();
  value.setDate(value.getDate() + days);
  const year = value.getFullYear();
  const month = String(value.getMonth() + 1).padStart(2, "0");
  const day = String(value.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

export function HoldEnrollmentDialog({
  enrollmentId,
  studentName,
  onClose,
  onHeld,
}: {
  enrollmentId: string | null;
  studentName: string;
  onClose: () => void;
  onHeld: () => void;
}) {
  const [returnOn, setReturnOn] = useState(() => dateInputValueFromOffset(30));
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const mutation = useMutation({
    mutationFn: () => holdEnrollment(enrollmentId!, { return_on: returnOn, reason: reason || null }),
    onSuccess: () => {
      setReturnOn(dateInputValueFromOffset(30));
      setReason("");
      setError(null);
      onHeld();
    },
    onError: (err: Error) => setError(err.message ?? "Could not hold enrollment."),
  });

  return (
    <RallyDialog
      open={enrollmentId !== null}
      onOpenChange={(open) => !open && onClose()}
      title="Hold enrollment"
      description={
        enrollmentId ? `Hold ${studentName}'s place — the seat stays theirs until they return.` : ""
      }
      overline="Lifecycle"
    >
      {error && <DialogError message={error} />}
      <form
        className="space-y-3"
        onSubmit={(event) => {
          event.preventDefault();
          mutation.mutate();
        }}
      >
        <Field label="Return date" required>
          <input
            type="date"
            required
            value={returnOn}
            onChange={(event) => setReturnOn(event.target.value)}
            className={inputClass}
          />
        </Field>
        <Field label="Reason">
          <textarea
            value={reason}
            onChange={(event) => setReason(event.target.value)}
            rows={3}
            className={inputClass}
          />
        </Field>
        <p className="text-xs text-rally-subtle">
          A hold keeps the seat — unlike pausing, which releases it — and the child is expected back
          on the return date.
        </p>
        <DialogActions>
          <Button variant="secondary" size="sm" type="button" onClick={onClose}>
            Cancel
          </Button>
          <Button variant="primary" size="sm" type="submit" disabled={!returnOn || mutation.isPending}>
            {mutation.isPending ? "Holding..." : "Hold"}
          </Button>
        </DialogActions>
      </form>
    </RallyDialog>
  );
}

export function ReturnFromHoldDialog({
  enrollmentId,
  studentName,
  onClose,
  onReturned,
}: {
  enrollmentId: string | null;
  studentName: string;
  onClose: () => void;
  onReturned: () => void;
}) {
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const mutation = useMutation({
    mutationFn: () => returnFromHold(enrollmentId!, { reason: reason || null }),
    onSuccess: () => {
      setReason("");
      setError(null);
      onReturned();
    },
    onError: (err: Error) => setError(err.message ?? "Could not return enrollment from hold."),
  });

  return (
    <RallyDialog
      open={enrollmentId !== null}
      onOpenChange={(open) => !open && onClose()}
      title="Return from hold"
      description={enrollmentId ? `Return ${studentName} to class.` : ""}
      overline="Lifecycle"
    >
      {error && <DialogError message={error} />}
      <form
        className="space-y-3"
        onSubmit={(event) => {
          event.preventDefault();
          mutation.mutate();
        }}
      >
        <Field label="Reason">
          <textarea
            value={reason}
            onChange={(event) => setReason(event.target.value)}
            rows={3}
            className={inputClass}
          />
        </Field>
        <p className="text-xs text-rally-subtle">
          The seat they were holding becomes active again and billing resumes.
        </p>
        <DialogActions>
          <Button variant="secondary" size="sm" type="button" onClick={onClose}>
            Cancel
          </Button>
          <Button variant="primary" size="sm" type="submit" disabled={mutation.isPending}>
            {mutation.isPending ? "Returning..." : "Return"}
          </Button>
        </DialogActions>
      </form>
    </RallyDialog>
  );
}
