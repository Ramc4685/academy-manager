"use client";

import type { ReactNode } from "react";

interface LaneLineProps {
  label?: string;
  dark?: boolean;
  mt?: number;
  mb?: number;
}

/**
 * Court-boundary divider used between sections.
 * Thick volt-yellow band + thin slate line, optional mono caption.
 */
export function LaneLine({ label, dark = false, mt = 0, mb = 0 }: LaneLineProps) {
  return (
    <div
      className="flex items-center gap-3"
      style={{ marginTop: mt, marginBottom: mb }}
    >
      <span className="flex-1 h-[3px] bg-rally-volt-400" />
      <span
        className="flex-1 h-px"
        style={{ background: dark ? "#334155" : "#cbd5e1" }}
      />
      {label && (
        <span
          className="font-mono text-[10px] font-bold tracking-lane uppercase"
          style={{ color: dark ? "#94a3b8" : "#64748b" }}
        >
          {label}
        </span>
      )}
      <span
        className="flex-1 h-px"
        style={{ background: dark ? "#334155" : "#cbd5e1" }}
      />
      <span className="flex-1 h-[3px] bg-rally-volt-400" />
    </div>
  );
}

interface LaneHeaderProps {
  index?: string | number | null;
  title: ReactNode;
  action?: ReactNode;
  dark?: boolean;
}

/** Compact lane-line section header (left aligned). */
export function LaneHeader({ index, title, action, dark = false }: LaneHeaderProps) {
  return (
    <div className="flex items-center gap-3.5 mb-4">
      {index != null && (
        <span
          className="font-mono text-[11px] font-bold tracking-lane rounded-[3px] px-2 py-[3px]"
          style={{
            color: dark ? "#facc15" : "#a16207",
            background: dark ? "rgba(250,204,21,0.1)" : "#fef9c3",
          }}
        >
          {index}
        </span>
      )}
      <h3
        className="font-display text-lg font-semibold tracking-[-0.01em] m-0"
        style={{ color: dark ? "#f1f5f9" : "#0f172a" }}
      >
        {title}
      </h3>
      <span
        className="flex-1 h-px"
        style={{ background: dark ? "#1e293b" : "#e2e8f0" }}
      />
      {action}
    </div>
  );
}
