"use client";

import { ConfirmActionDialog } from "@/components/ds/confirm-action-dialog";

/** S71: what an absence and a make-up are, in GLOSSARY.md's terms. */
export const ABSENCE_HELP =
  "Tell us before class starts that your child will miss a class date. Their seat is kept and the bill does not change; with enough notice, they can make it up on another class date within the academy's make-up window.";
export const MAKEUP_HELP =
  "A make-up is another class date your child attends instead of one they missed, within the academy's make-up window. It adds nothing to your bill.";

/** S17: the second look before an absence reaches the coach. */
export function AbsenceConfirmDialog({
  open,
  onOpenChange,
  childName,
  sessionTitle,
  when,
  pending,
  onConfirm,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  childName: string;
  sessionTitle: string;
  when: string;
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
      consequence="The coach is told before class. Calendar and Home show the class as absent. Your child keeps their seat, and with enough notice the class can be made up on another date."
      confirmLabel="Report absence"
      cancelLabel="Keep the class"
      confirmVariant="primary"
      pending={pending}
      onConfirm={onConfirm}
    />
  );
}
