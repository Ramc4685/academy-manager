"use client";

import { Button, Card, Chip, Overline } from "@/components/ds";
import type { AdminFamilyBillingView, FamilyRecordView } from "@/lib/api/admin-families";
import { lifecycleLabel, lifecycleVariant } from "@/lib/format/lifecycle-copy";
import { formatCents } from "@/lib/money";

import { childTriggerId, type OverviewChild } from "./family-record";

/**
 * Overview (People CRM spec §4): who the family is at a glance. The stage and
 * children come from the family index row (the Families view's own row), the
 * money line only when `money_visible` says this caller may see amounts.
 * Every child opens the child drawer.
 */
export function OverviewTab({
  record,
  billing,
  kids,
  onOpenChild,
}: {
  record: FamilyRecordView | null;
  billing: AdminFamilyBillingView | null;
  kids: OverviewChild[];
  onOpenChild: (studentId: string) => void;
}) {
  const money = record?.money_visible ? record.family.money : null;
  const autopay = billing?.header.autopay ?? null;
  return (
    <div className="space-y-4" data-testid="family-overview">
      <div className="grid gap-3 sm:grid-cols-3">
        <Card p={16}>
          <Overline>Children</Overline>
          <p className="mt-1 font-display text-2xl font-semibold text-rally-ink">{kids.length}</p>
        </Card>
        {money && (
          <Card p={16} data-testid="family-overview-balance">
            <Overline>Balance</Overline>
            <p className="mt-1 font-display text-2xl font-semibold text-rally-ink">
              {formatCents(money.balance_cents)}
            </p>
            <p className="text-xs text-rally-muted">
              {money.overdue_invoice_count > 0
                ? `${money.overdue_invoice_count} overdue`
                : `${money.open_invoice_count} open`}
            </p>
          </Card>
        )}
        {autopay && (
          <Card p={16}>
            <Overline>Autopay</Overline>
            <p className="mt-1 text-sm font-semibold text-rally-ink">
              {autopay.state === "on"
                ? "On"
                : autopay.state === "partial"
                  ? `On for ${autopay.active_count} of ${autopay.total_count}`
                  : autopay.state === "needs_consent"
                    ? "Needs parent consent"
                    : "Off"}
            </p>
          </Card>
        )}
      </div>

      <Card p={20}>
        <Overline>Children</Overline>
        {kids.length === 0 ? (
          <p className="mt-2 text-sm text-rally-muted">No children on this family yet.</p>
        ) : (
          <ul className="mt-2 divide-y divide-rally-line" data-testid="family-overview-children">
            {kids.map((kid) => (
              <li
                key={kid.studentId}
                className="flex flex-wrap items-center justify-between gap-3 py-3"
                data-testid={`family-overview-child-${kid.studentId}`}
              >
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-medium text-rally-ink">{kid.name}</span>
                    {kid.lifecycle && (
                      <Chip
                        variant={lifecycleVariant(kid.lifecycle)}
                        label={lifecycleLabel(kid.lifecycle, kid.lifecycleAsOf)}
                      />
                    )}
                  </div>
                  <p className="text-xs text-rally-muted">
                    {kid.classes.length > 0 ? kid.classes.join(" · ") : "Not in a class"}
                  </p>
                </div>
                <Button
                  size="sm"
                  variant="secondary"
                  id={childTriggerId(kid.studentId)}
                  data-testid={childTriggerId(kid.studentId)}
                  aria-haspopup="dialog"
                  onClick={() => onOpenChild(kid.studentId)}
                >
                  View {kid.name}
                </Button>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}
