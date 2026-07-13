"use client";

import type { CSSProperties, ReactNode } from "react";

export type ChipVariant =
  | "paid" | "pending" | "failed" | "overdue" | "refunded" | "partial"
  | "waived" | "nocharge" | "autopayOn" | "autopayPend" | "manual"
  | "waitlist" | "offered" | "expired" | "enrolled" | "approval"
  | "paused" | "transferred" | "present" | "absent" | "late"
  | "excused" | "makeup" | "full" | "open" | "closing" | "approved" | "draft"
  | "denied" | "converted";

interface ChipSpec {
  bg: string;
  fg: string;
  dot: string;
  label: string;
}

export const CHIP_VARIANTS: Record<ChipVariant, ChipSpec> = {
  paid:        { bg: "#ecfdf5", fg: "#065f46", dot: "#10b981", label: "PAID" },
  pending:     { bg: "#fffbeb", fg: "#92400e", dot: "#f59e0b", label: "PENDING" },
  failed:      { bg: "#fef2f2", fg: "#991b1b", dot: "#ef4444", label: "FAILED" },
  overdue:     { bg: "#fef2f2", fg: "#991b1b", dot: "#dc2626", label: "OVERDUE" },
  refunded:    { bg: "#f1f5f9", fg: "#334155", dot: "#64748b", label: "REFUNDED" },
  partial:     { bg: "#f1f5f9", fg: "#334155", dot: "#64748b", label: "PARTIAL" },
  waived:      { bg: "#f1f5f9", fg: "#334155", dot: "#94a3b8", label: "WAIVED" },
  nocharge:    { bg: "#f1f5f9", fg: "#334155", dot: "#94a3b8", label: "NO CHARGE" },
  autopayOn:   { bg: "#eff6ff", fg: "#1e40af", dot: "#2563eb", label: "AUTOPAY" },
  autopayPend: { bg: "#eff6ff", fg: "#1e40af", dot: "#60a5fa", label: "AUTOPAY PENDING" },
  manual:      { bg: "#f1f5f9", fg: "#334155", dot: "#64748b", label: "MANUAL" },
  waitlist:    { bg: "#fefce8", fg: "#854d0e", dot: "#eab308", label: "WAITLIST" },
  offered:     { bg: "#fefce8", fg: "#854d0e", dot: "#facc15", label: "OFFER SENT" },
  expired:     { bg: "#f1f5f9", fg: "#475569", dot: "#64748b", label: "EXPIRED" },
  enrolled:    { bg: "#ecfdf5", fg: "#065f46", dot: "#10b981", label: "ENROLLED" },
  approval:    { bg: "#fffbeb", fg: "#92400e", dot: "#f59e0b", label: "NEEDS APPROVAL" },
  paused:      { bg: "#f1f5f9", fg: "#334155", dot: "#94a3b8", label: "PAUSED" },
  transferred: { bg: "#f1f5f9", fg: "#334155", dot: "#94a3b8", label: "TRANSFERRED" },
  present:     { bg: "#ecfdf5", fg: "#065f46", dot: "#10b981", label: "PRESENT" },
  absent:      { bg: "#fef2f2", fg: "#991b1b", dot: "#ef4444", label: "ABSENT" },
  late:        { bg: "#fffbeb", fg: "#92400e", dot: "#f59e0b", label: "LATE" },
  excused:     { bg: "#f1f5f9", fg: "#334155", dot: "#64748b", label: "EXCUSED" },
  makeup:      { bg: "#eff6ff", fg: "#1e40af", dot: "#3b82f6", label: "MAKE-UP" },
  full:        { bg: "#fef2f2", fg: "#991b1b", dot: "#ef4444", label: "FULL" },
  open:        { bg: "#ecfdf5", fg: "#065f46", dot: "#10b981", label: "OPEN" },
  closing:     { bg: "#fffbeb", fg: "#92400e", dot: "#f59e0b", label: "CLOSING" },
  approved:    { bg: "#ecfdf5", fg: "#065f46", dot: "#10b981", label: "APPROVED" },
  draft:       { bg: "#f1f5f9", fg: "#475569", dot: "#94a3b8", label: "DRAFT" },
  denied:      { bg: "#fef2f2", fg: "#991b1b", dot: "#ef4444", label: "DENIED" },
  converted:   { bg: "#ecfdf5", fg: "#065f46", dot: "#10b981", label: "CONVERTED" },
};

interface ChipProps {
  variant?: ChipVariant;
  label?: ReactNode;
  dark?: boolean;
}

export function Chip({ variant = "paid", label, dark = false }: ChipProps) {
  const v = CHIP_VARIANTS[variant] ?? CHIP_VARIANTS.paid;
  const text = label ?? v.label;
  const style: CSSProperties = {
    background: dark ? "rgba(255,255,255,0.05)" : v.bg,
    color: dark ? "#e2e8f0" : v.fg,
  };
  return (
    <span
      className="inline-flex items-center gap-1.5 rounded-[3px] px-2 py-[3px] pr-2 pl-[7px] font-mono text-[10px] font-bold tracking-chip leading-[1.4] whitespace-nowrap"
      style={style}
    >
      <span
        className="size-1.5 shrink-0 rounded-full"
        style={{
          background: v.dot,
          boxShadow: dark ? `0 0 6px ${v.dot}99` : "none",
        }}
      />
      {text}
    </span>
  );
}
