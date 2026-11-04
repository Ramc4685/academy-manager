"use client";

import { useId, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import {
  getAttendanceRisk,
  getFamiliesLost,
  getInquiryConversion,
  getMoneyOwedByAge,
} from "@/lib/api/admin";
import { departureReasonLabel } from "@/lib/admin/departure-reasons";
import { queryKeys } from "@/lib/query/keys";
import { formatCents, formatDateOnly } from "@/lib/money";
import {
  familiesText,
  isMoneyHidden,
  normalizeAttendanceRisk,
  normalizeFamiliesLost,
  normalizeInquiry,
  normalizeMoneyOwed,
  studentsText,
  type RiskRow,
} from "@/lib/people-reports-view";
import { Card } from "@/components/ds/card";
import { Overline } from "@/components/ds/typography";
import { Skeleton } from "@/components/ds/skeleton";
import { EmptyState } from "@/components/ds/empty-state";

/**
 * People reports (roadmap L5a): money owed by age band, and inquiry to
 * enrolled by source. L5b adds attendance risk by class and coach, and
 * families lost and why. Plain tables, never a color-only chart: every number
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

function DateRange({
  from,
  to,
  onFrom,
  onTo,
  testId,
}: {
  from: string;
  to: string;
  onFrom: (value: string) => void;
  onTo: (value: string) => void;
  testId: string;
}) {
  const fromId = useId();
  const toId = useId();
  return (
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
          onChange={(event) => onFrom(event.target.value)}
          className="rounded-md border border-rally-line px-2 py-1"
          data-testid={`${testId}-from`}
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
          onChange={(event) => onTo(event.target.value)}
          className="rounded-md border border-rally-line px-2 py-1"
          data-testid={`${testId}-to`}
        />
      </div>
    </div>
  );
}

function RiskTable({
  rows,
  kind,
  caption,
}: {
  rows: RiskRow[];
  kind: "class" | "coach";
  caption: string;
}) {
  return (
    <div className="mt-3 overflow-x-auto">
      <table className={TABLE} data-testid={`people-report-risk-${kind}-table`}>
        <caption className="sr-only">{caption}</caption>
        <thead>
          <tr className="border-b border-rally-line">
            <th scope="col" className={TH}>
              {kind === "class" ? "Class" : "Coach"}
            </th>
            {kind === "class" ? (
              <th scope="col" className={TH}>
                Coach
              </th>
            ) : (
              <th scope="col" className={TH_NUM}>
                Classes
              </th>
            )}
            <th scope="col" className={TH_NUM}>
              Students
            </th>
            <th scope="col" className={TH_NUM}>
              At risk
            </th>
            <th scope="col" className={TH_NUM}>
              Share
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr
              key={row.key}
              className="border-b border-rally-line/60"
              data-testid={`people-report-risk-${kind}-row-${row.key}`}
            >
              <th scope="row" className={`${TD} text-left font-normal`}>
                {row.label}
              </th>
              {kind === "class" ? (
                <td className={TD}>{row.coach}</td>
              ) : (
                <td className={TD_NUM}>{row.classes}</td>
              )}
              <td className={TD_NUM}>{row.students}</td>
              <td className={TD_NUM}>{row.atRisk}</td>
              <td className={TD_NUM}>{row.share}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function AttendanceRiskPanel() {
  const { data, isLoading, isError } = useQuery({
    queryKey: queryKeys.admin.attendanceRisk(),
    queryFn: getAttendanceRisk,
  });
  const view = normalizeAttendanceRisk(data);

  return (
    <Card p={24} data-testid="people-report-attendance-risk">
      <Overline>Attendance risk by class and coach</Overline>
      <p className="mt-1 text-sm text-rally-subtle">
        Students with no attendance in their class&apos;s last three class dates, the same rule
        as the At risk tab on Students.
      </p>

      {isError ? (
        <p role="alert" className="mt-4 text-sm text-red-700">
          Could not load attendance risk. Try again in a minute.
        </p>
      ) : isLoading ? (
        <div className="mt-4">
          <Skeleton variant="block" height="8rem" />
        </div>
      ) : !view || view.byClass.length === 0 ? (
        <EmptyState
          className="mt-4"
          compact
          title="No students in a class right now"
          description="Classes with students will appear here with how many stopped coming."
          data-testid="people-report-attendance-risk-empty"
        />
      ) : (
        <>
          <p className="mt-3 text-sm text-rally-ink" data-testid="people-report-attendance-risk-total">
            {studentsText(view.atRisk)} at risk of {studentsText(view.students)} in a class.
          </p>
          <h3 className="mt-4 text-sm font-semibold text-rally-ink">By class</h3>
          <RiskTable rows={view.byClass} kind="class" caption="At-risk students by class" />
          <h3 className="mt-4 text-sm font-semibold text-rally-ink">By coach</h3>
          <RiskTable rows={view.byCoach} kind="coach" caption="At-risk students by coach" />
          <p className="mt-3 text-xs text-rally-muted">
            A student in two classes is counted in each class and once per coach. Classes that
            have met fewer than three times flag nobody yet.
          </p>
        </>
      )}
    </Card>
  );
}

export function FamiliesLostPanel() {
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const { data, isLoading, isError } = useQuery({
    queryKey: queryKeys.admin.familiesLost(from, to),
    queryFn: () => getFamiliesLost({ from, to }),
  });
  const view = normalizeFamiliesLost(data);

  return (
    <Card p={24} data-testid="people-report-families-lost">
      <Overline>Families lost and why</Overline>
      <p className="mt-1 text-sm text-rally-subtle">
        Families whose children have all left, counted on the day the last class ended.
        {from || to ? "" : " Last 90 days."}
      </p>

      <DateRange
        from={from}
        to={to}
        onFrom={setFrom}
        onTo={setTo}
        testId="people-report-families-lost"
      />

      {isError ? (
        <p role="alert" className="mt-4 text-sm text-red-700">
          Could not load families lost for these dates. Check that From is before To.
        </p>
      ) : isLoading ? (
        <div className="mt-4">
          <Skeleton variant="block" height="8rem" />
        </div>
      ) : !view || view.familiesLost === 0 ? (
        <EmptyState
          className="mt-4"
          compact
          title="No families left in these dates"
          description="Families whose children all leave will appear here with the reason given."
          data-testid="people-report-families-lost-empty"
        />
      ) : (
        <div className="mt-4 overflow-x-auto">
          <table className={TABLE} data-testid="people-report-families-lost-table">
            <caption className="sr-only">
              Families lost from {formatDateOnly(view.dateFrom)} to {formatDateOnly(view.dateTo)}
            </caption>
            <thead>
              <tr className="border-b border-rally-line">
                <th scope="col" className={TH}>
                  Reason
                </th>
                <th scope="col" className={TH_NUM}>
                  Families
                </th>
              </tr>
            </thead>
            {view.reasons.length > 0 ? (
              <tbody>
                {view.reasons.map((row) => (
                  <tr
                    key={row.key}
                    className="border-b border-rally-line/60"
                    data-testid={`people-report-families-lost-reason-${row.key}`}
                  >
                    <th scope="row" className={`${TD} text-left font-normal`}>
                      {departureReasonLabel(row.key) ?? row.key}
                    </th>
                    <td className={TD_NUM}>{row.families}</td>
                  </tr>
                ))}
              </tbody>
            ) : null}
            {view.transitions.length > 0 ? (
              <tbody data-testid="people-report-families-lost-no-reason">
                <tr>
                  <th
                    scope="rowgroup"
                    colSpan={2}
                    className="pt-3 pb-1 text-left text-xs font-semibold text-rally-subtle"
                  >
                    No reason recorded, by how they left
                  </th>
                </tr>
                {view.transitions.map((row) => (
                  <tr
                    key={row.key}
                    className="border-b border-rally-line/60"
                    data-testid={`people-report-families-lost-transition-${row.key}`}
                  >
                    <th scope="row" className={`${TD} text-left font-normal`}>
                      {row.label ?? row.key}
                    </th>
                    <td className={TD_NUM}>{row.families}</td>
                  </tr>
                ))}
              </tbody>
            ) : null}
            <tfoot>
              <tr data-testid="people-report-families-lost-total">
                <th scope="row" className={`${TD} text-left font-semibold`}>
                  Families lost
                </th>
                <td className={`${TD_NUM} font-semibold`}>{view.familiesLost}</td>
              </tr>
            </tfoot>
          </table>
        </div>
      )}
      {view && view.familiesLost > 0 ? (
        <p className="mt-3 text-xs text-rally-muted">
          {view.withoutReason > 0
            ? `${familiesText(view.withoutReason)} left with no reason recorded, so they are counted by how their last class ended. `
            : ""}
          {formatDateOnly(view.dateFrom)} to {formatDateOnly(view.dateTo)}
          {view.timezone ? ` (${view.timezone})` : ""}.
        </p>
      ) : null}
    </Card>
  );
}
