"use client";

import type { ReactNode } from "react";

export type ChipVariant =
  | "paid" | "pending" | "failed" | "overdue" | "refunded" | "partial"
  | "waived" | "nocharge" | "autopayOn" | "autopayPend" | "manual"
  | "waitlist" | "offered" | "expired" | "enrolled" | "approval"
  | "paused" | "transferred" | "present" | "absent" | "late"
  | "excused" | "makeup" | "full" | "open" | "closing" | "approved" | "draft"
  | "denied" | "converted";

interface ChipSpec {
  box: string;
  dot: string;
  label: string;
}

// Shared color families — 30 semantic variants collapse onto these classes.
const GREEN = "bg-status-green-50 text-status-green-800";
const AMBER = "bg-status-amber-50 text-status-amber-800";
const RED = "bg-status-red-50 text-status-red-800";
const SLATE = "bg-status-slate-100 text-status-slate-700";
const SLATE_MID = "bg-status-slate-100 text-status-slate-600";
const BLUE = "bg-rally-cobalt-50 text-status-blue-800";
const YELLOW = "bg-status-yellow-50 text-status-yellow-800";

const GREEN_DOT = "bg-status-green-500";
const AMBER_DOT = "bg-status-amber-500";
const RED_DOT = "bg-status-red-500";
const MUTED_DOT = "bg-rally-muted";
const FAINT_DOT = "bg-rally-subtle-ink";

export const CHIP_VARIANTS: Record<ChipVariant, ChipSpec> = {
  paid:        { box: GREEN, dot: GREEN_DOT, label: "PAID" },
  pending:     { box: AMBER, dot: AMBER_DOT, label: "PENDING" },
  failed:      { box: RED, dot: RED_DOT, label: "FAILED" },
  overdue:     { box: RED, dot: "bg-status-red-600", label: "OVERDUE" },
  refunded:    { box: SLATE, dot: MUTED_DOT, label: "REFUNDED" },
  partial:     { box: SLATE, dot: MUTED_DOT, label: "PARTIAL" },
  waived:      { box: SLATE, dot: FAINT_DOT, label: "WAIVED" },
  nocharge:    { box: SLATE, dot: FAINT_DOT, label: "NO CHARGE" },
  autopayOn:   { box: BLUE, dot: "bg-rally-cobalt-600", label: "AUTOPAY" },
  autopayPend: { box: BLUE, dot: "bg-status-blue-400", label: "AUTOPAY PENDING" },
  manual:      { box: SLATE, dot: MUTED_DOT, label: "MANUAL" },
  waitlist:    { box: YELLOW, dot: "bg-rally-volt-500", label: "WAITLIST" },
  offered:     { box: YELLOW, dot: "bg-rally-volt-400", label: "OFFER SENT" },
  expired:     { box: SLATE_MID, dot: MUTED_DOT, label: "EXPIRED" },
  enrolled:    { box: GREEN, dot: GREEN_DOT, label: "ENROLLED" },
  approval:    { box: AMBER, dot: AMBER_DOT, label: "NEEDS APPROVAL" },
  paused:      { box: SLATE, dot: FAINT_DOT, label: "PAUSED" },
  transferred: { box: SLATE, dot: FAINT_DOT, label: "TRANSFERRED" },
  present:     { box: GREEN, dot: GREEN_DOT, label: "PRESENT" },
  absent:      { box: RED, dot: RED_DOT, label: "ABSENT" },
  late:        { box: AMBER, dot: AMBER_DOT, label: "LATE" },
  excused:     { box: SLATE, dot: MUTED_DOT, label: "EXCUSED" },
  makeup:      { box: BLUE, dot: "bg-rally-cobalt-500", label: "MAKE-UP" },
  full:        { box: RED, dot: RED_DOT, label: "FULL" },
  open:        { box: GREEN, dot: GREEN_DOT, label: "OPEN" },
  closing:     { box: AMBER, dot: AMBER_DOT, label: "CLOSING" },
  approved:    { box: GREEN, dot: GREEN_DOT, label: "APPROVED" },
  draft:       { box: SLATE_MID, dot: FAINT_DOT, label: "DRAFT" },
  denied:      { box: RED, dot: RED_DOT, label: "DENIED" },
  converted:   { box: GREEN, dot: GREEN_DOT, label: "CONVERTED" },
};

interface ChipProps {
  variant?: ChipVariant;
  label?: ReactNode;
}

export function Chip({ variant = "paid", label }: ChipProps) {
  const v = CHIP_VARIANTS[variant] ?? CHIP_VARIANTS.paid;
  const text = label ?? v.label;
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-[3px] px-2 py-[3px] pr-2 pl-[7px] font-mono text-[10px] font-bold tracking-chip leading-[1.4] whitespace-nowrap ${v.box}`}
    >
      <span className={`size-1.5 shrink-0 rounded-full ${v.dot}`} />
      {text}
    </span>
  );
}
