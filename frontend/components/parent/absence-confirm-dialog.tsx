"use client";

import { ConfirmActionDialog } from "@/components/ds/confirm-action-dialog";

/** S17: the second look before an absence reaches the coach. */
export function AbsenceConfirmDialog({
  open,
  onOpenChange,
  childName,
  sessionTitle,
  when,
  reason,
  onReasonChange,
  pending,
  onConfirm,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  childName: string;
  sessionTitle: string;
  when: string;
  reason: string;
  onReasonChange: (value: string) => void;
  pending: boolean;
  onConfirm: () => void;
}) {
  return (
    <ConfirmActionDialog
      open={open}
      onOpenChange={onOpenChange}
      overline="Report absence"
      title={`${childName} will miss this class?`}
      subject={`${sessionTitle} · ${when}`}
      consequence="The coach is told before class. Calendar and Home show the class as absent."
      confirmLabel="Report absence"
      cancelLabel="Keep the class"
      confirmVariant="primary"
      pending={pending}
      reason={{
        label: "Reason (optional)",
        value: reason,
        onChange: onReasonChange,
        placeholder: "For example: family trip",
      }}
      onConfirm={onConfirm}
    />
  );
}
