import type { CSSProperties } from "react";

type SkeletonVariant = "line" | "block" | "circle";

interface SkeletonProps {
  variant?: SkeletonVariant;
  width?: string | number;
  height?: string | number;
  lines?: number;
  className?: string;
}

const RADIUS: Record<SkeletonVariant, string> = {
  line: "rounded",
  block: "rounded-lg",
  circle: "rounded-full",
};

const DEFAULT_HEIGHT: Record<SkeletonVariant, string> = {
  line: "0.75rem",
  block: "4rem",
  circle: "2.5rem",
};

/** Token-based loading placeholder built on the `shimmer` keyframes in globals.css. */
export function Skeleton({ variant = "line", width, height, lines = 1, className }: SkeletonProps) {
  const base = `shimmer ${RADIUS[variant]}`;
  const h = height ?? DEFAULT_HEIGHT[variant];
  const w = width ?? (variant === "circle" ? h : "100%");
  const style: CSSProperties = { width: w, height: h };

  if (variant === "line" && lines > 1) {
    return (
      <div className={`space-y-2 ${className ?? ""}`} aria-hidden="true">
        {Array.from({ length: lines }).map((_, i) => (
          <div
            key={i}
            className={base}
            style={{ ...style, width: i === lines - 1 ? "60%" : style.width }}
          />
        ))}
      </div>
    );
  }

  return <div className={`${base} ${className ?? ""}`} style={style} aria-hidden="true" />;
}

interface TableSkeletonProps {
  rows?: number;
  cols?: number;
  className?: string;
}

/** Canonical home for the per-page table loading helper duplicated across admin monoliths. */
export function TableSkeleton({ rows = 3, cols = 1, className }: TableSkeletonProps) {
  return (
    <div className={`space-y-2 ${className ?? ""}`} aria-hidden="true">
      {Array.from({ length: rows }).map((_, r) => (
        <div key={r} className="flex gap-3">
          {Array.from({ length: cols }).map((_, c) => (
            <div key={c} className="h-14 flex-1 rounded-lg shimmer" />
          ))}
        </div>
      ))}
    </div>
  );
}
