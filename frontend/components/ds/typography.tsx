"use client";

import type { CSSProperties, ReactNode } from "react";

interface BigNumProps {
  children: ReactNode;
  size?: number;
  color?: string;
  delta?: ReactNode;
  deltaTone?: "pos" | "neg" | "neutral";
}

/** Big tabular display numeric — Outfit, tight tracking. */
export function BigNum({
  children,
  size = 44,
  color,
  delta,
  deltaTone = "pos",
}: BigNumProps) {
  const deltaColor =
    deltaTone === "pos"
      ? "#059669"
      : deltaTone === "neg"
        ? "#dc2626"
        : "#64748b";
  return (
    <div className="flex items-baseline gap-2">
      <span
        className="font-display font-bold tracking-[-0.03em] leading-none tabular-nums"
        style={{ fontSize: size, color: color ?? "#0f172a" }}
      >
        {children}
      </span>
      {delta && (
        <span
          className="font-mono text-[11px] font-bold"
          style={{ color: deltaColor }}
        >
          {delta}
        </span>
      )}
    </div>
  );
}

interface OverlineProps {
  children: ReactNode;
  color?: string;
  style?: CSSProperties;
}

/** Mono uppercase caption. */
export function Overline({ children, color, style }: OverlineProps) {
  return (
    <div
      className="font-mono text-[10px] font-bold tracking-overline uppercase"
      style={{ color: color ?? "#64748b", ...style }}
    >
      {children}
    </div>
  );
}
