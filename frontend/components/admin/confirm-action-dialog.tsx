"use client";

import { useState, type ReactNode } from "react";

import { Button } from "@/components/ds/button";
import { Field, RallyModal } from "@/components/ds/dialog-chrome";

/**
 * Issue #838: the one second-look dialog for high-impact admin actions.
 *
 * Built on `RallyModal` so every instance inherits the DS focus trap, the
 * Escape handler and focus restore — the three things the native `confirm()`
 * calls this replaced could not offer. The shape is the void-invoice dialog's:
 * overline, the item restated, a consequence sentence, an optional required
 * reason, and a danger-outline confirm.
 */
export function ConfirmActionDialog({
  open,
  onOpenChange,
  overline,
  title,
  /** The person, family, session or batch being acted on, restated verbatim. */
  subject,
  /** What actually happens — seat, invoice/autopay, and what the family is emailed. */
  consequence,
  confirmLabel,
  confirmVariant = "danger",
  pending = false,
  /** When present, the confirm button stays disabled until it is filled in. */
  reason,
  error,
  children,
  onConfirm,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  overline: string;
  title: string;
  subject?: ReactNode;
  consequence: ReactNode;
  confirmLabel: string;
  confirmVariant?: "primary" | "danger";
  pending?: boolean;
  reason?: {
    label: string;
    value: string;
    onChange: (value: string) => void;
    required?: boolean;
    placeholder?: string;
  };
  error?: string | null;
  children?: ReactNode;
  onConfirm: () => void;
}) {
  // A blank required reason must block the request, not be swapped for a
  // canned one (#838). Track it here so every caller gets the same rule.
  const reasonMissing = Boolean(reason?.required) && !(reason?.value ?? "").trim();

  return (
    <RallyModal
      open={open}
      onOpenChange={onOpenChange}
      overline={overline}
      title={title}
      description=""
    >
      <form
        data-testid="confirm-action-dialog"
        className="space-y-3"
        onSubmit={(event) => {
          event.preventDefault();
          // The modal portals out of the DOM but stays in the React tree, so
          // without this a confirm inside a host <form> re-submits that form.
          event.stopPropagation();
          if (reasonMissing || pending) return;
          onConfirm();
        }}
      >
        {subject && (
          <p className="rounded-md border border-rally-line bg-rally-paper px-3 py-2 text-sm font-semibold text-rally-ink">
            {subject}
          </p>
        )}

        <div className="space-y-2 text-sm text-rally-muted">{consequence}</div>

        {children}

        {reason && (
          <Field label={reason.label} required={reason.required}>
            <textarea
              value={reason.value}
              onChange={(event) => reason.onChange(event.target.value)}
              placeholder={reason.placeholder}
              required={reason.required}
              rows={3}
              className="w-full rounded-md border border-neutral-200 bg-white px-3 py-2 text-sm text-rally-base outline-none focus:border-rally-cobalt-600 focus:ring-2 focus:ring-rally-cobalt-600/15"
            />
          </Field>
        )}

        {reasonMissing && (
          <p className="text-[12px] text-rally-muted" data-testid="confirm-action-reason-required">
            A reason is required — it is recorded and shown to whoever reviews this later.
          </p>
        )}

        {error && (
          <p role="alert" className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">
            {error}
          </p>
        )}

        <div className="flex justify-end gap-2 pt-1">
          <Button
            type="button"
            variant="secondary"
            size="sm"
            onClick={() => onOpenChange(false)}
            disabled={pending}
          >
            Keep as is
          </Button>
          <Button
            type="submit"
            variant={confirmVariant}
            size="sm"
            disabled={pending || reasonMissing}
            data-testid="confirm-action-submit"
          >
            {pending ? "Working…" : confirmLabel}
          </Button>
        </div>
      </form>
    </RallyModal>
  );
}

/**
 * Small helper for the callers that open the dialog from a row: holds the
 * pending target and clears it on close, so the dialog never renders a stale
 * name for a split second while it animates out.
 */
export function useConfirmTarget<T>(): {
  target: T | null;
  open: (value: T) => void;
  close: () => void;
  onOpenChange: (open: boolean) => void;
} {
  const [target, setTarget] = useState<T | null>(null);
  return {
    target,
    open: (value: T) => setTarget(value),
    close: () => setTarget(null),
    onOpenChange: (next: boolean) => {
      if (!next) setTarget(null);
    },
  };
}

