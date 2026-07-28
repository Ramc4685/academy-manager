"use client";

/**
 * Franchise rollup — revenue and outstanding dues across every academy the
 * signed-in user owns (UIM11). The academy set comes from the server's read
 * of the caller's own `owner` memberships, not from the active-academy
 * header, so this page shows the same figures whichever academy is active.
 */

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";

import { getOwnerRollup } from "@/lib/api/v2/owner";
import { queryKeys } from "@/lib/query/keys";
import { formatMoney } from "@/lib/parent-home";
import { setActiveAcademyId } from "@/lib/api/client";
import { Card, EmptyState, TableSkeleton } from "@/components/ds";

export default function OwnerRollupPage() {
  const rollup = useQuery({
    queryKey: queryKeys.owner.rollup(),
    queryFn: () => getOwnerRollup(),
    retry: false,
  });

  return (
    <div className="flex flex-col gap-5">
      <div>
        <h1 className="font-display text-2xl font-bold text-rally-ink">All academies</h1>
        <p className="mt-1 text-sm text-rally-muted">
          Consolidated revenue and outstanding dues across the academies you own.
        </p>
      </div>

      {rollup.isPending && <TableSkeleton data-testid="owner-rollup-loading" />}

      {rollup.isError && (
        <EmptyState
          title="Franchise rollup unavailable"
          description="This view is only available to franchise owners. If you believe you should have access, contact support."
          data-testid="owner-rollup-denied"
        />
      )}

      {rollup.data && rollup.data.academies.length === 0 && (
        <EmptyState
          title="No academies yet"
          description="You do not own any academies."
          data-testid="owner-rollup-empty"
        />
      )}

      {rollup.data && rollup.data.academies.length > 0 && (
        <>
          <div className="grid gap-3 sm:grid-cols-3" data-testid="owner-rollup-totals">
            <TotalTile label="Academies" value={String(rollup.data.totals.academy_count)} />
            <TotalTile
              label="Collected"
              value={formatMoney(rollup.data.totals.collected_cents)}
            />
            <TotalTile
              label="Outstanding"
              value={formatMoney(rollup.data.totals.outstanding_cents)}
              hint={`${rollup.data.totals.outstanding_invoice_count} open invoices`}
            />
          </div>

          <Card>
            <div className="overflow-x-auto">
              <table className="w-full text-sm" data-testid="owner-rollup-table">
                <thead>
                  <tr className="border-b border-rally-line text-left">
                    <Th>Academy</Th>
                    <Th align="right">Collected</Th>
                    <Th align="right">Outstanding</Th>
                    <Th align="right">Open invoices</Th>
                  </tr>
                </thead>
                <tbody>
                  {rollup.data.academies.map((row) => (
                    <tr
                      key={row.academy_id}
                      className="border-b border-rally-line last:border-0"
                      data-testid={`owner-rollup-row-${row.academy_id}`}
                    >
                      <td className="px-3 py-2">
                        <Link
                          href="/admin"
                          onClick={() => setActiveAcademyId(row.academy_id)}
                          className="font-medium text-rally-cobalt-600 hover:underline"
                        >
                          {row.academy_name ?? row.academy_id}
                        </Link>
                      </td>
                      <td className="px-3 py-2 text-right tabular-nums">
                        {formatMoney(row.collected_cents)}
                      </td>
                      <td className="px-3 py-2 text-right tabular-nums">
                        {formatMoney(row.outstanding_cents)}
                      </td>
                      <td className="px-3 py-2 text-right tabular-nums">
                        {row.outstanding_invoice_count}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        </>
      )}
    </div>
  );
}

function TotalTile({
  label,
  value,
  hint,
}: {
  label: string;
  value: string;
  hint?: string;
}) {
  return (
    <Card>
      <div className="font-mono text-[10px] font-bold tracking-overline text-rally-muted">
        {label}
      </div>
      <div className="mt-1 font-display text-xl font-bold tabular-nums text-rally-ink">
        {value}
      </div>
      {hint && <div className="mt-0.5 text-[11px] text-rally-muted">{hint}</div>}
    </Card>
  );
}

function Th({
  children,
  align = "left",
}: {
  children: React.ReactNode;
  align?: "left" | "right";
}) {
  return (
    <th
      className={`px-3 py-2 font-mono text-[10px] font-bold tracking-overline text-rally-muted ${
        align === "right" ? "text-right" : "text-left"
      }`}
    >
      {children}
    </th>
  );
}
