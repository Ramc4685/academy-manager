import { Chip } from "@/components/ds";
import type { FamilyMoneyDisplay } from "@/lib/family-money-view";
import { formatCents } from "@/lib/money";

/**
 * One family's money in a list cell (L2b, #553): the balance for owner,
 * admin and billing; an "Owes money" flag with no amount for front desk.
 * `unknown` reads as unknown, never $0.00.
 */
export function FamilyMoneyCell({
  display,
  testId,
}: {
  display: FamilyMoneyDisplay;
  testId?: string;
}) {
  switch (display.kind) {
    case "hidden":
      return null;
    case "unknown":
      return (
        <span className="text-rally-subtle" title="Balance unknown" data-testid={testId}>
          —
        </span>
      );
    case "owes":
      return <OwesMoneyChip testId={testId} />;
    case "clear":
      return (
        <span className="text-xs text-rally-muted" data-testid={testId}>
          Paid up
        </span>
      );
    case "amount":
      return (
        <span className="flex flex-col items-end" data-testid={testId}>
          <span
            className={`font-mono tabular-nums ${
              display.balanceCents > 0 ? "font-semibold text-status-red-800" : "text-rally-muted"
            }`}
          >
            {formatCents(display.balanceCents)}
          </span>
          {display.overdueCount > 0 ? (
            <span className="text-[11px] text-status-red-800">
              {formatCents(display.overdueCents)} overdue
            </span>
          ) : null}
        </span>
      );
  }
}

/** The front-desk flag: says the family owes money, never how much. */
export function OwesMoneyChip({ testId }: { testId?: string }) {
  return (
    <span data-testid={testId} title="This family has an unpaid balance.">
      <Chip variant="overdue" label="Owes money" />
    </span>
  );
}

/**
 * The family record header's flag: shown only when the family owes money and
 * this caller sees the flag rather than amounts (front desk, or an owner
 * previewing front desk). Amount viewers read the balance on Overview.
 */
export function FamilyOwesFlag({ display }: { display: FamilyMoneyDisplay }) {
  if (display.kind !== "owes") return null;
  return <OwesMoneyChip testId="family-record-owes-money" />;
}
