"use client";

import { useId, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { getInquiryConversion, getMoneyOwedByAge } from "@/lib/api/admin";
import { queryKeys } from "@/lib/query/keys";
import { formatCents, formatDateOnly } from "@/lib/money";
import {
  familiesText,
  isMoneyHidden,
  normalizeInquiry,
  normalizeMoneyOwed,
} from "@/lib/people-reports-view";
import { Card } from "@/components/ds/card";
import { Overline } from "@/components/ds/typography";
import { Skeleton } from "@/components/ds/skeleton";
import { EmptyState } from "@/components/ds/empty-state";

/**
 * People reports (roadmap L5a): money owed by age band, and inquiry to
 * enrolled by source. Plain tables, never a color-only chart: every number
 * is text a screen reader reads in row and column order.
 */

const TABLE = "w-full min-w-[20rem] text-sm";
const TH =
  "py-2 pr-3 text-left font-mono text-[10px] font-bold uppercase tracking-overline text-rally-muted";
const TH_NUM = `${TH} text-right`;
const TD = "py-2 pr-3 text-rally-ink";
const TD_NUM = `${TD} text-right tabular-nums`;

export function MoneyOwedByAgePanel() {
  const { data, error, isLoading, isError } = useQuery({
    queryKey: queryKeys.admin.moneyOwedByAge(),
    queryFn: getMoneyOwedByAge,
    retry: (failures, err) => !isMoneyHidden(err) && failures < 2,
  });

  // A role that may not see family money gets 403: no card at all.
  if (isError && isMoneyHidden(error)) return null;

  const view = normalizeMoneyOwed(data);

  return (
    <Card p={24} data-testid="people-report-money-owed">
      <Overline>Money owed by age</Overline>
      <p className="mt-1 text-sm text-rally-subtle">
        Open invoice balances by how many days past due, after payments and credits.
      </p>

      {isError ? (
        <p role="alert" className="mt-4 text-sm text-red-700">
          Could not load money owed. Try again in a minute.
        </p>
      ) : isLoading ? (
        <div className="mt-4">
          <Skeleton variant="block" height="8rem" />
        </div>
      ) : !view || view.owingFamilies === 0 ? (
        <EmptyState
          className="mt-4"
          compact
          title="No family owes money right now"
          description="Open balances will appear here by how late they are."
          data-testid="people-report-money-owed-empty"
        />
      ) : (
        <div className="mt-4 overflow-x-auto">
          <table className={TABLE} data-testid="people-report-money-owed-table">
            <caption className="sr-only">
              Money owed by days past due, as of {formatDateOnly(view.asOf)}
            </caption>
            <thead>
              <tr className="border-b border-rally-line">
                <th scope="col" className={TH}>
                  Age
                </th>
                <th scope="col" className={TH_NUM}>
                  Families
                </th>
                <th scope="col" className={TH_NUM}>
                  Amount
                </th>
              </tr>
            </thead>
            <tbody>
              {view.rows.map((row) => (
                <tr
                  key={row.key}
                  className="border-b border-rally-line/60"
                  data-testid={`people-report-money-owed-row-${row.key}`}
                >
                  <th scope="row" className={`${TD} text-left font-normal`}>
                    {row.label}
                  </th>
                  <td className={TD_NUM}>{familiesText(row.familyCount)}</td>
                  <td className={TD_NUM}>{formatCents(row.totalCents)}</td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr data-testid="people-report-money-owed-total">
                <th scope="row" className={`${TD} text-left font-semibold`}>
                  Total owed
                </th>
                <td className={`${TD_NUM} font-semibold`}>{familiesText(view.owingFamilies)}</td>
                <td className={`${TD_NUM} font-semibold`}>{formatCents(view.balanceCents)}</td>
              </tr>
            </tfoot>
          </table>
        </div>
      )}
      {view && view.owingFamilies > 0 ? (
        <p className="mt-3 text-xs text-rally-muted">
          {formatCents(view.overdueCents)} is past due across {familiesText(view.overdueFamilies)}.
          A family with invoices of different ages is counted in each band. As of{" "}
          {formatDateOnly(view.asOf)}.
        </p>
      ) : null}
    </Card>
  );
}

export function InquiryConversionPanel() {
  const fromId = useId();
  const toId = useId();
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const { data, isLoading, isError } = useQuery({
    queryKey: queryKeys.admin.inquiryConversion(from, to),
    queryFn: () => getInquiryConversion({ from, to }),
  });
  const view = normalizeInquiry(data);

  return (
    <Card p={24} data-testid="people-report-inquiries">
      <Overline>Inquiries to enrolled, by source</Overline>
      <p className="mt-1 text-sm text-rally-subtle">
        People who asked about classes and how many reached a trial or enrolled.
        {from || to ? "" : " Last 90 days."}
      </p>

      <div className="mt-3 flex flex-wrap items-end gap-3 text-sm">
        <div className="flex flex-col gap-1">
          <label htmlFor={fromId} className="text-rally-subtle">
            From
          </label>
          <input
            id={fromId}
            type="date"
            value={from}
            max={to || undefined}
            onChange={(event) => setFrom(event.target.value)}
            className="rounded-md border border-rally-line px-2 py-1"
            data-testid="people-report-inquiries-from"
          />
        </div>
        <div className="flex flex-col gap-1">
          <label htmlFor={toId} className="text-rally-subtle">
            To
          </label>
          <input
            id={toId}
            type="date"
            value={to}
            min={from || undefined}
            onChange={(event) => setTo(event.target.value)}
            className="rounded-md border border-rally-line px-2 py-1"
            data-testid="people-report-inquiries-to"
          />
        </div>
      </div>

      {isError ? (
        <p role="alert" className="mt-4 text-sm text-red-700">
          Could not load inquiries for these dates. Check that From is before To.
        </p>
      ) : isLoading ? (
        <div className="mt-4">
          <Skeleton variant="block" height="8rem" />
        </div>
      ) : !view || view.total.inquiries === 0 ? (
        <EmptyState
          className="mt-4"
          compact
          title="No inquiries in these dates"
          description="Website trial requests and inquiries staff add will appear here."
          data-testid="people-report-inquiries-empty"
        />
      ) : (
        <div className="mt-4 overflow-x-auto">
          <table className={TABLE} data-testid="people-report-inquiries-table">
            <caption className="sr-only">
              Inquiries by source from {formatDateOnly(view.dateFrom)} to{" "}
              {formatDateOnly(view.dateTo)}
            </caption>
            <thead>
              <tr className="border-b border-rally-line">
                <th scope="col" className={TH}>
                  Source
                </th>
                <th scope="col" className={TH_NUM}>
                  Inquiries
                </th>
                <th scope="col" className={TH_NUM}>
                  Lead
                </th>
                <th scope="col" className={TH_NUM}>
                  Trial
                </th>
                <th scope="col" className={TH_NUM}>
                  Enrolled
                </th>
                <th scope="col" className={TH_NUM}>
                  Enrolled rate
                </th>
              </tr>
            </thead>
            <tbody>
              {view.rows.map((row) => (
                <tr
                  key={row.source}
                  className="border-b border-rally-line/60"
                  data-testid={`people-report-inquiries-row-${row.source}`}
                >
                  <th scope="row" className={`${TD} text-left font-normal`}>
                    {row.label}
                  </th>
                  <td className={TD_NUM}>{row.inquiries}</td>
                  <td className={TD_NUM}>{row.lead}</td>
                  <td className={TD_NUM}>{row.trial}</td>
                  <td className={TD_NUM}>{row.enrolled}</td>
                  <td className={TD_NUM}>{row.conversion}</td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr data-testid="people-report-inquiries-total">
                <th scope="row" className={`${TD} text-left font-semibold`}>
                  {view.total.label}
                </th>
                <td className={`${TD_NUM} font-semibold`}>{view.total.inquiries}</td>
                <td className={`${TD_NUM} font-semibold`}>{view.total.lead}</td>
                <td className={`${TD_NUM} font-semibold`}>{view.total.trial}</td>
                <td className={`${TD_NUM} font-semibold`}>{view.total.enrolled}</td>
                <td className={`${TD_NUM} font-semibold`}>{view.total.conversion}</td>
              </tr>
            </tfoot>
          </table>
        </div>
      )}
      {view && view.total.inquiries > 0 ? (
        <p className="mt-3 text-xs text-rally-muted">
          {formatDateOnly(view.dateFrom)} to {formatDateOnly(view.dateTo)}
          {view.timezone ? ` (${view.timezone})` : ""}. Counted by the day the inquiry came in.
        </p>
      ) : null}
    </Card>
  );
}
