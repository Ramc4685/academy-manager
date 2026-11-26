"use client";

/**
 * S10: an unpriced class (fee never set, the server's `unpriced` flag) bills
 * nothing. Staff see it on the class header and acknowledge it before they
 * enroll a child into it. A free class (fee 0) is priced and shows neither.
 * Pricing itself stays owner-only.
 */

export const UNPRICED_CLASS_MESSAGE = "No price set. The owner must set one before billing.";

export function UnpricedClassBanner() {
  return (
    <p
      role="status"
      data-testid="session-unpriced-banner"
      className="mt-2 rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-sm font-medium text-amber-900"
    >
      {UNPRICED_CLASS_MESSAGE}
    </p>
  );
}

export function UnpricedEnrollAcknowledgement({
  checked,
  onChange,
}: {
  checked: boolean;
  onChange: (next: boolean) => void;
}) {
  return (
    <label
      data-testid="unpriced-enroll-ack"
      className="flex items-start gap-2 rounded-md border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900"
    >
      <input
        type="checkbox"
        className="mt-0.5 h-4 w-4"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
      />
      <span>
        This class has no price yet, so this child will not be billed until the owner sets one. Enroll
        anyway.
      </span>
    </label>
  );
}
