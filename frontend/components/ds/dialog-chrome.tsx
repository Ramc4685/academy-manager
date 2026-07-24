import type { ReactNode } from "react";

import { Button } from "./button";
import { Modal } from "./modal";
import { Overline } from "./typography";

/**
 * Superset of the RallyDialog wrapper duplicated across the admin sessions
 * and payments pages. Renders on top of the DS `Modal` primitive (MT5/DS3).
 */
export function RallyModal({
  open,
  onOpenChange,
  title,
  description,
  overline,
  children,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  title: string;
  description: string;
  overline: string;
  children: ReactNode;
}) {
  return (
    <Modal
      open={open}
      onClose={() => onOpenChange(false)}
      size="md"
      title={
        <>
          <Overline>{overline}</Overline>
          <div className="mt-1 font-display text-xl font-semibold tracking-[-0.01em]">{title}</div>
        </>
      }
    >
      <div className="max-h-[70vh] overflow-y-auto">
        {description && <p className="mb-1 text-sm text-rally-muted">{description}</p>}
        {children}
      </div>
    </Modal>
  );
}

export function DialogError({ message }: { message: string }) {
  return (
    <p role="alert" className="mb-3 rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">
      {message}
    </p>
  );
}

/**
 * Superset of the two DialogActions shapes duplicated across admin pages:
 * pass `children` for manually-composed buttons (sessions), or
 * `onCancel`+`submitLabel` for the default Cancel/Submit pair (payments).
 */
export function DialogActions({
  onCancel,
  submitLabel,
  children,
}: {
  onCancel?: () => void;
  submitLabel?: string;
  children?: ReactNode;
}) {
  if (children) {
    return <div className="flex justify-end gap-2 pt-2">{children}</div>;
  }
  return (
    <div className="flex justify-end gap-2 pt-2">
      <Button variant="secondary" size="sm" type="button" onClick={onCancel}>
        Cancel
      </Button>
      <Button variant="primary" size="sm" type="submit">
        {submitLabel}
      </Button>
    </div>
  );
}

export function Field({
  label,
  required,
  children,
}: {
  label: string;
  required?: boolean;
  children: ReactNode;
}) {
  return (
    <label className="block">
      <span className="mb-1 block font-mono text-[10px] font-bold uppercase tracking-overline text-rally-muted">
        {label}
        {required && (
          <span aria-hidden="true" className="ml-1 text-red-500">
            *
          </span>
        )}
      </span>
      {children}
    </label>
  );
}

export function Th({
  children,
  align = "left",
  className,
}: {
  children: ReactNode;
  align?: "left" | "right";
  className?: string;
}) {
  return (
    <th
      className={`px-4 py-3 font-mono text-[10px] font-bold uppercase tracking-overline text-rally-muted ${
        align === "right" ? "text-right" : "text-left"
      } ${className ?? ""}`}
    >
      {children}
    </th>
  );
}
