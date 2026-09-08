"use client";

import Link from "next/link";

import { Button, Card, Chip, Overline } from "@/components/ds";
import type { AdminFamilyBillingView } from "@/lib/api/admin-families";
import { formatCents, formatInstantDay } from "@/lib/money";

import { autopayToggle, registrationChip } from "./family-view";

export function FamilyHeader({
  view,
  busy,
  onToggleAutopay,
  onSendInvite,
  onSendInvoice,
  onRecordPayment,
}: {
  view: AdminFamilyBillingView;
  busy: boolean;
  onToggleAutopay: (turnOn: boolean) => void;
  onSendInvite: () => void;
  onSendInvoice: () => void;
  onRecordPayment: () => void;
}) {
  const { parent, header, actions } = view;
  const toggle = autopayToggle(header.autopay);
  const reg = registrationChip(header.registration.state);
  const studentCount = view.students.length;
  return (
    <Card p={20}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h1 className="font-display text-xl font-semibold text-rally-ink">
            {parent.name ?? "Parent"}
          </h1>
          <p className="text-sm text-rally-muted">
            {parent.email ?? "no email"} · {studentCount}{" "}
            {studentCount === 1 ? "student" : "students"}
            {parent.phone ? ` · ${parent.phone}` : ""}
          </p>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <span data-testid="family-registration-chip">
              <Chip variant={reg.variant} label={reg.label} />
            </span>
            {actions.includes("send_invite") && (
              <Button
                size="sm"
                variant="secondary"
                data-testid="family-send-invite"
                onClick={onSendInvite}
                disabled={busy}
              >
                {header.registration.last_invited_at ? "Resend invite" : "Send invite"}
              </Button>
            )}
            <Link
              href={`/admin/messages?dm=${encodeURIComponent(parent.parent_id)}`}
              className="text-sm text-rally-cobalt-700 hover:underline"
            >
              Message
            </Link>
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          {actions.includes("send_invoice") && (
            <Button
              size="sm"
              variant="secondary"
              data-testid="family-send-invoice"
              onClick={onSendInvoice}
              disabled={busy}
            >
              Send invoice
            </Button>
          )}
          {actions.includes("record_payment") && (
            <Button
              size="sm"
              variant="primary"
              data-testid="family-record-payment"
              onClick={onRecordPayment}
              disabled={busy}
            >
              Record payment
            </Button>
          )}
        </div>
      </div>

      <div className="mt-5 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Tile
          overline="Balance"
          testId="family-balance"
          big={formatCents(header.balance_cents)}
          sub={`${header.open_invoice_count} open ${header.open_invoice_count === 1 ? "invoice" : "invoices"}${
            header.available_credit_cents > 0
              ? ` · ${formatCents(header.available_credit_cents)} credit`
              : ""
          }`}
        />
        <div className="rounded-xl border border-rally-line p-3">
          <Overline>Autopay</Overline>
          <label className="mt-1 flex items-center gap-3">
            <input
              type="checkbox"
              role="switch"
              data-testid="family-autopay-toggle"
              aria-label="Autopay"
              aria-checked={toggle.checked}
              checked={toggle.checked}
              disabled={toggle.disabled || busy}
              onChange={(e) => onToggleAutopay(e.target.checked)}
              className="size-5 accent-rally-cobalt-600"
            />
            <span className="font-display text-lg font-semibold text-rally-ink">
              {toggle.label}
            </span>
          </label>
          <p className="mt-1 text-xs text-rally-muted" data-testid="family-autopay-hint">
            {toggle.hint}
          </p>
          {header.autopay.last_failure?.code && (
            <p className="mt-1 text-xs text-status-red-600">
              Last failure: {header.autopay.last_failure.code}
            </p>
          )}
        </div>
        <Tile
          overline="Last payment"
          testId="family-last-payment"
          big={header.last_payment ? formatCents(header.last_payment.amount_cents) : "—"}
          sub={
            header.last_payment
              ? `${formatInstantDay(header.last_payment.paid_at)} · ${header.last_payment.method ?? "payment"}`
              : "No payments yet"
          }
        />
        <Tile
          overline="Enrollments"
          testId="family-enrollments"
          big={String(header.enrollment_counts.active + header.enrollment_counts.paused)}
          sub={`${header.enrollment_counts.active} active · ${header.enrollment_counts.paused} paused`}
        />
      </div>
    </Card>
  );
}

function Tile({
  overline,
  big,
  sub,
  testId,
}: {
  overline: string;
  big: string;
  sub: string;
  testId: string;
}) {
  return (
    <div className="rounded-xl border border-rally-line p-3" data-testid={testId}>
      <Overline>{overline}</Overline>
      <div className="mt-1 font-display text-lg font-semibold text-rally-ink">{big}</div>
      <p className="text-xs text-rally-muted">{sub}</p>
    </div>
  );
}
