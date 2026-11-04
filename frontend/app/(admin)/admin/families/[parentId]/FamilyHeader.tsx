"use client";

import Link from "next/link";

import { Button, Card, Chip, ContactLinks, Overline } from "@/components/ds";
import type { AdminFamilyBillingView } from "@/lib/api/admin-families";
import { formatCents, formatInstantDay } from "@/lib/money";

import { describeCardDeclineCode } from "@/lib/people-status";

import {
  autopayToggle,
  familyRefundLine,
  refundLabel,
  registrationChips,
  undeliverableChip,
} from "./family-view";

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
  const reg = registrationChips(header.registration.state);
  const undeliverable = undeliverableChip(header.email_delivery);
  const studentCount = view.students.length;
  const lastPaymentRefund = header.last_payment
    ? refundLabel(
        header.last_payment.amount_cents,
        header.last_payment.refunded_cents,
        header.last_payment.net_cents,
      )
    : null;
  const familyRefunds = familyRefundLine(header);
  return (
    <Card p={20}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h1 className="font-display text-xl font-semibold text-rally-ink">
            {parent.name ?? "Parent"}
          </h1>
          <p className="text-sm text-rally-muted">
            {studentCount} {studentCount === 1 ? "student" : "students"}
          </p>
          {/* #865: the email and the number were plain text here, so the one
              thing an admin opens this page to do — reach the family about the
              money on it — started with a copy-paste. */}
          <ContactLinks
            className="mt-0.5 text-sm text-rally-muted"
            data-testid="family-contacts"
            name={parent.name ?? undefined}
            email={parent.email}
            phone={parent.phone}
            fallback="No contact details on file"
          />
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <span data-testid="family-login-chip">
              <Chip variant={reg.login.variant} label={reg.login.label} />
            </span>
            <span data-testid="family-registration-chip">
              <Chip variant={reg.card.variant} label={reg.card.label} />
            </span>
            {undeliverable && (
              <span data-testid="family-undeliverable-chip">
                <Chip variant={undeliverable.variant} label={undeliverable.label} />
              </span>
            )}
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
            {/* #839: the family page owned the money but had no way through to
                the login account behind it — the chips above name its state,
                and this is where you go to do something about it. */}
            <Link
              href={`/admin/users/${encodeURIComponent(parent.parent_id)}`}
              className="rounded text-sm text-rally-cobalt-700 hover:underline focus:outline-none focus:ring-2 focus:ring-rally-cobalt-600"
              data-testid="family-account-link"
            >
              Account &amp; login
            </Link>
          </div>
          {undeliverable && (
            <p
              className="mt-2 text-xs text-status-red-600"
              data-testid="family-undeliverable-detail"
            >
              {undeliverable.detail}
            </p>
          )}
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
          {/* #840: "Last failure: card_declined" was a Stripe developer string
              with nothing to do about it. Say what happened, then offer the way
              out that belongs to the card — the invite that replaces it.

              #890: this card used to carry a second "Record payment" on the
              same `onRecordPayment` handler as the header's primary button, so
              the page offered the action three times (here, the header, and
              every owing invoice row). Recording a payment is not specific to
              the autopay failure, so it stays where it is general: the header. */}
          {header.autopay.last_failure && (
            <div className="mt-1" data-testid="family-autopay-failure">
              <p className="text-xs text-status-red-600">
                {describeCardDeclineCode(header.autopay.last_failure.code)}
              </p>
              <div className="mt-1.5 flex flex-wrap gap-2">
                <Button
                  size="sm"
                  variant="secondary"
                  data-testid="family-failure-resend-invite"
                  onClick={onSendInvite}
                  disabled={busy}
                >
                  Resend card invite
                </Button>
              </div>
            </div>
          )}
        </div>
        <Tile
          overline="Last payment"
          testId="family-last-payment"
          big={header.last_payment ? formatCents(header.last_payment.amount_cents) : "—"}
          sub={
            header.last_payment
              ? `${formatInstantDay(header.last_payment.paid_at)} · ${header.last_payment.method ?? "payment"}${
                  lastPaymentRefund ? ` · ${lastPaymentRefund}` : ""
                }`
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
      {/* #929: refunds used to be invisible here; the family totals say what came back. */}
      {familyRefunds && (
        <p className="mt-3 text-xs text-rally-muted" data-testid="family-refunds">
          {familyRefunds}
        </p>
      )}
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
