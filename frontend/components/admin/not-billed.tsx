"use client";

import { useMutation } from "@tanstack/react-query";
import { useState } from "react";

import { Button, FormField, Modal } from "@/components/ds";
import {
  setEnrollmentBilling,
  type EnrollmentBillingView,
  type NotBilledReason,
} from "@/lib/api/v2/students";

export const NOT_BILLED_REASON_LABELS: Record<NotBilledReason, string> = {
  owner_child: "Owner's child",
  coach_child: "Coach's child",
  scholarship: "Scholarship",
  other: "Other",
};

/** `Owner's child`, the note for Other, or `null` when no reason is on record. */
export function notBilledReasonText(
  reason: string | null | undefined,
  note?: string | null,
): string | null {
  if (!reason) return null;
  if (reason === "other" && note) return note;
  return (NOT_BILLED_REASON_LABELS as Record<string, string>)[reason] ?? null;
}

/** "Not billed · Owner's child" wherever a class row shows billing. */
export function NotBilledChip({
  reason,
  note,
}: {
  reason?: string | null;
  note?: string | null;
}) {
  const why = notBilledReasonText(reason, note);
  return (
    <span
      data-testid="not-billed-chip"
      className="inline-flex items-center rounded-full bg-neutral-100 px-2 py-0.5 text-xs font-medium text-rally-muted"
    >
      Not billed{why ? ` · ${why}` : ""}
    </span>
  );
}

/** " · +2 not billed" next to a headcount; empty when there are none. */
export function notBilledSuffix(count: number | null | undefined): string {
  return count ? ` · +${count} not billed` : "";
}

const INPUT =
  "w-full rounded-lg border border-rally-line bg-white px-3 py-2 text-sm text-rally-ink outline-none focus:border-rally-cobalt";

/**
 * Owner only: "Not billed" (reason, note, optionally void open invoices) or
 * "Start billing" (invoices again from next month). Going forward only.
 */
export function NotBilledDialog({
  enrollmentId,
  className,
  notBilled,
  onClose,
  onSaved,
}: {
  enrollmentId: string | null;
  className?: string | null;
  notBilled: boolean;
  onClose: () => void;
  onSaved: (result: EnrollmentBillingView) => void;
}) {
  const [reason, setReason] = useState<NotBilledReason | "">("");
  const [note, setNote] = useState("");
  const [voidOpen, setVoidOpen] = useState(false);
  const mutation = useMutation({
    mutationFn: () =>
      setEnrollmentBilling(
        enrollmentId!,
        notBilled
          ? { not_billed: false }
          : {
              not_billed: true,
              reason: reason || null,
              note: note.trim() || null,
              void_open_invoices: voidOpen,
            },
      ),
    onSuccess: (result) => {
      setReason("");
      setNote("");
      setVoidOpen(false);
      onSaved(result);
    },
  });
  const close = () => {
    mutation.reset();
    onClose();
  };
  const invalid = !notBilled && (!reason || (reason === "other" && !note.trim()));

  return (
    <Modal
      open={enrollmentId !== null}
      onClose={close}
      title={notBilled ? "Start billing" : "Not billed"}
      dismissable={!mutation.isPending}
      footer={
        <div className="flex justify-end gap-2">
          <Button variant="ghost" size="sm" onClick={close} disabled={mutation.isPending}>
            Cancel
          </Button>
          <Button
            size="sm"
            data-testid="not-billed-save"
            disabled={invalid || mutation.isPending}
            onClick={() => mutation.mutate()}
          >
            {mutation.isPending ? "Saving…" : notBilled ? "Start billing" : "Mark not billed"}
          </Button>
        </div>
      }
    >
      {notBilled ? (
        <p className="text-sm text-rally-subtle">
          {className ?? "This class"} is invoiced again from next month. This month stays
          unbilled.
        </p>
      ) : (
        <div className="space-y-3">
          <p className="text-sm text-rally-subtle">
            {className ?? "This class"} is left off every monthly run from now on. The child
            stays on rosters, attendance and skills but out of headcounts.
          </p>
          <FormField label="Reason" htmlFor="not-billed-reason" required>
            <select
              id="not-billed-reason"
              className={INPUT}
              value={reason}
              onChange={(e) => setReason(e.target.value as NotBilledReason | "")}
            >
              <option value="">Choose…</option>
              {Object.entries(NOT_BILLED_REASON_LABELS).map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
          </FormField>
          <FormField
            label="Note"
            htmlFor="not-billed-note"
            required={reason === "other"}
            hint="Saved in the billing audit log."
          >
            <input
              id="not-billed-note"
              maxLength={500}
              className={INPUT}
              value={note}
              onChange={(e) => setNote(e.target.value)}
            />
          </FormField>
          <label className="flex items-start gap-2 text-sm text-rally-ink">
            <input
              type="checkbox"
              className="mt-0.5"
              checked={voidOpen}
              onChange={(e) => setVoidOpen(e.target.checked)}
            />
            <span>
              Also void this class&apos;s open invoices
              <span className="block text-xs text-rally-subtle">
                Invoices with a payment on them are kept.
              </span>
            </span>
          </label>
        </div>
      )}
      {mutation.error && (
        <p role="alert" className="mt-3 text-xs font-medium text-status-red-800">
          {(mutation.error as Error).message}
        </p>
      )}
    </Modal>
  );
}
