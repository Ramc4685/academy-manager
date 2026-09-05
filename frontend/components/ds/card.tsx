"use client";

import type { CSSProperties, ReactNode } from "react";

interface CardProps {
  children: ReactNode;
  p?: number;
  accent?: string;
  style?: CSSProperties;
  className?: string;
  /** Test hook for cards whose presence is itself the assertion. */
  "data-testid"?: string;
}

export function Card({ children, p = 24, accent, style, className, ...rest }: CardProps) {
  const inline: CSSProperties = {
    padding: p,
    // accent is an arbitrary caller-supplied color, so it stays inline.
    ...(accent ? { borderTop: `3px solid ${accent}` } : {}),
    ...style,
  };
  return (
    <div
      className={`relative overflow-hidden rounded-xl border border-rally-line bg-white ${className ?? ""}`}
      style={inline}
      data-testid={rest["data-testid"]}
    >
      {children}
    </div>
  );
}
