import type { ReactNode } from "react";

interface EmptyStateProps {
  icon?: ReactNode;
  title: string;
  description?: ReactNode;
  action?: ReactNode;
  compact?: boolean;
  className?: string;
  "data-testid"?: string;
}

export function EmptyState({
  icon,
  title,
  description,
  action,
  compact = false,
  className,
  ...rest
}: EmptyStateProps) {
  return (
    <div
      className={`flex flex-col items-center justify-center text-center ${
        compact ? "gap-1 py-4" : "gap-2 py-10"
      } ${className ?? ""}`}
      {...rest}
    >
      {icon && <div className="text-rally-muted">{icon}</div>}
      <p className={`font-semibold text-rally-ink ${compact ? "text-sm" : "text-base"}`}>{title}</p>
      {description && <p className="max-w-sm text-sm text-rally-subtle">{description}</p>}
      {action && <div className="mt-1">{action}</div>}
    </div>
  );
}
