"use client";

import type { CSSProperties, ReactNode } from "react";

interface CardProps {
  children: ReactNode;
  p?: number;
  accent?: string;
  style?: CSSProperties;
  className?: string;
}

export function Card({ children, p = 24, accent, style, className }: CardProps) {
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
    >
      {children}
    </div>
  );
}
