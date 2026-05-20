"use client";

import type { CSSProperties, ReactNode } from "react";

interface CardProps {
  children: ReactNode;
  dark?: boolean;
  p?: number;
  accent?: string;
  style?: CSSProperties;
  className?: string;
}

export function Card({ children, dark = false, p = 24, accent, style, className }: CardProps) {
  const inline: CSSProperties = {
    background: dark ? "#0b1220" : "#fff",
    border: `1px solid ${dark ? "#1e293b" : "#e2e8f0"}`,
    padding: p,
    ...(accent ? { borderTop: `3px solid ${accent}` } : {}),
    ...style,
  };
  return (
    <div
      className={`relative overflow-hidden rounded-xl ${className ?? ""}`}
      style={inline}
    >
      {children}
    </div>
  );
}
