"use client";

/**
 * S60: a coach's own classes taught and released payslip, one month at a time
 * (docs/design/coach-pay.md). Online only: the query is never persisted
 * (`shouldPersistQuery`) nor cached by the service worker, and `gcTime: 0`
 * drops the figures from memory when the coach leaves the page.
 */

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import {
  BigNum,
  Button,
  Card,
  Chip,
  ContactLinks,
  EmptyState,
  ErrorNotice,
  LaneHeader,
  Overline,
  PhoneList,
  PhoneListRow,
  Skeleton,
} from "@/components/ds";
import { getCoachAcademy, getCoachPay, type CoachPay } from "@/lib/api/coach";
import { academyMonthKey, formatAcademyClock, formatAcademyDate } from "@/lib/format/academy-time";
import { formatCents, formatDateOnly } from "@/lib/money";
import { queryKeys } from "@/lib/query/keys";
import { formatTaught } from "./format-taught";

/** The month stepper goes back to the current month and the 23 before it. */
const MONTHS_BACK = 23;

const ROLE_LABEL = { lead: "Lead", cover: "Cover", assistant: "Assistant" } as const;

/** "9 h 30 min"; "45 min" under an hour. */

function spokenTaught(minutes: number): string {
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  const parts = [h ? `${h} hour${h === 1 ? "" : "s"}` : "", m || !h ? `${m} minute${m === 1 ? "" : "s"}` : ""];
  return parts.filter(Boolean).join(" ");
}

/** "Nov 1" from "2026-11-01". */
function shortDay(value: string | null | undefined): string {
  return formatDateOnly(value).replace(/, \d{4}$/, "");
}

function monthName(label: string): string {
  return label.split(" ")[0] ?? label;
}

function Payslip({ pay }: { pay: CoachPay }) {
  const slip = pay.payslip;
  if (!slip) {
    return (
      <Card p={16} data-testid="pay-no-payslip">
        <p className="text-sm text-rally-base">
          No payslip for {monthName(pay.month_label)} yet. It appears here once the academy approves it.
        </p>
      </Card>
    );
  }
  const paid = slip.status === "paid";
  const amount = paid && slip.paid_amount_cents != null ? slip.paid_amount_cents : slip.total_cents;
  return (
    <Card p={16} data-testid="pay-payslip">
      <div className="flex items-center justify-between gap-3">
        <p className="text-sm font-medium">
          {shortDay(slip.period_start)} – {shortDay(slip.period_end)}
        </p>
        <Chip variant={paid ? "paid" : "approved"} />
      </div>
      <div className="mt-2">
        <BigNum size={28}>{formatCents(amount)}</BigNum>
      </div>
      <p className="mt-2 text-sm text-neutral-600 dark:text-neutral-300">
        {paid
          ? `Paid ${shortDay(slip.paid_on)}${slip.paid_method_label ? ` by ${slip.paid_method_label}` : ""}.`
          : `Approved ${shortDay(slip.approved_on)}. Not paid yet.`}
      </p>
      {paid && slip.paid_amount_cents != null && slip.paid_amount_cents !== slip.total_cents && (
        <p className="mt-1 text-sm text-neutral-600 dark:text-neutral-300" data-testid="pay-difference">
          Payslip total {formatCents(slip.total_cents)}, paid {formatCents(slip.paid_amount_cents)}. Ask the
          academy about the difference.
        </p>
      )}
    </Card>
  );
}

export default function CoachPayPage() {
  const heading = useRef<HTMLHeadingElement>(null);
  const [offset, setOffset] = useState(0);
  const { data: academy } = useQuery({ queryKey: queryKeys.coach.academy(), queryFn: getCoachAcademy });
  const tz = academy?.timezone ?? null;
  // Offset 0 lets the server decide "this month" on the academy clock.
  const month = offset === 0 ? undefined : academyMonthKey(tz, offset);
  const pay = useQuery({
    queryKey: queryKeys.coach.pay(month ?? "current"),
    queryFn: () => getCoachPay(month),
    gcTime: 0,
  });

  useEffect(() => heading.current?.focus(), []);

  const data = pay.data;
  const label = data?.month_label ?? (month ? "" : "This month");
  const offline = typeof navigator !== "undefined" && navigator.onLine === false;

  return (
    <section data-testid="coach-pay" className="mx-auto max-w-xl">
      <Link
        href="/coach/profile"
        className="inline-flex min-h-touch items-center text-sm text-rally-cobalt-700 underline-offset-2 hover:underline"
      >
        ← Profile
      </Link>
      <h1 ref={heading} tabIndex={-1} className="mb-4 text-2xl font-semibold focus:outline-none">
        Pay
      </h1>

      <Card p={16}>
        <div role="group" aria-label="Month" className="flex items-center justify-between gap-2">
          <Button
            variant="ghost"
            aria-label="Previous month"
            disabled={offset <= -MONTHS_BACK}
            onClick={() => setOffset((o) => o - 1)}
            className="min-h-touch min-w-touch"
          >
            ‹
          </Button>
          <p aria-live="polite" className="font-medium" data-testid="pay-month">
            {label}
          </p>
          <Button
            variant="ghost"
            aria-label="Next month"
            disabled={offset >= 0}
            onClick={() => setOffset((o) => o + 1)}
            className="min-h-touch min-w-touch"
          >
            ›
          </Button>
        </div>
        {pay.isPending ? (
          <div className="mt-4 grid grid-cols-2 gap-4">
            <Skeleton variant="block" height={48} />
            <Skeleton variant="block" height={48} />
          </div>
        ) : data ? (
          <dl className="mt-4 grid grid-cols-2 gap-4" data-testid="pay-stats">
            <div>
              <dt>
                <Overline>Classes taught</Overline>
              </dt>
              <dd>
                <BigNum size={32}>{data.classes_taught}</BigNum>
              </dd>
            </div>
            <div>
              <dt>
                <Overline>Time</Overline>
              </dt>
              <dd aria-label={spokenTaught(data.minutes_taught)}>
                <BigNum size={32}>{formatTaught(data.minutes_taught)}</BigNum>
              </dd>
            </div>
          </dl>
        ) : null}
      </Card>

      {pay.isError && (
        <ErrorNotice
          className="mt-4"
          testId="pay-error"
          message={`We could not load your pay. Check your connection and try again.${
            offline ? " Pay is only available online." : ""
          }`}
          onRetry={() => void pay.refetch()}
          retrying={pay.isFetching}
        />
      )}

      {pay.isPending && <Skeleton className="mt-6" lines={4} />}

      {data && (
        <>
          <div className="mt-6">
            <LaneHeader title="Payslip" />
            <Payslip pay={data} />
          </div>

          <div className="mt-6">
            <LaneHeader title="Classes" />
            {data.classes.length === 0 ? (
              <EmptyState
                compact
                title={`No classes taught in ${monthName(data.month_label)}`}
                description="Classes you teach appear here after they finish."
              />
            ) : (
              <PhoneList aria-label="Classes taught" data-testid="pay-classes">
                {data.classes.map((c) => (
                  <PhoneListRow
                    key={c.occurrence_id}
                    title={`${formatAcademyDate(c.start_at, tz)} · ${formatAcademyClock(c.start_at, tz)}`}
                    secondary={`${c.class_name} · ${c.minutes} min`}
                    primary={<span className="text-sm">{ROLE_LABEL[c.role]}</span>}
                  />
                ))}
              </PhoneList>
            )}
          </div>

          <div className="mt-6" data-testid="pay-how">
            <LaneHeader title="How you are paid" />
            <p className="text-sm text-neutral-700 dark:text-neutral-200">
              {data.academy_contact.name} works out pay after the month ends. Your payslip appears here when the
              academy approves it, and is marked Paid when they have paid you.
            </p>
            {data.academy_contact.phone || data.academy_contact.email ? (
              <div className="mt-1 text-sm text-neutral-700 dark:text-neutral-200">
                <span>Questions about your pay? </span>
                <ContactLinks
                  phone={data.academy_contact.phone}
                  email={data.academy_contact.email}
                  name={data.academy_contact.name}
                  className="inline-flex"
                />
              </div>
            ) : (
              <p className="mt-1 text-sm text-neutral-700 dark:text-neutral-200">
                Questions about your pay? Ask the academy owner.
              </p>
            )}
          </div>
        </>
      )}
    </section>
  );
}
