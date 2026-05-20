"use client";

import { useQuery } from "@tanstack/react-query";

import {
  listAdminWaivers,
  type AdminCurrentWaiverView,
  type AdminWaiverStatus,
  type AdminWaiverStudentRow,
  type AdminWaiverSummary,
} from "@/lib/api/admin";
import { queryKeys } from "@/lib/query/keys";
import { Avatar, BigNum, Card, Chip, LaneHeader, Overline } from "@/components/ds";

export default function AdminWaiversPage() {
  const waiversQuery = useQuery({
    queryKey: queryKeys.admin.waivers(),
    queryFn: () => listAdminWaivers(),
    retry: false,
  });

  if (waiversQuery.isError) {
    return (
      <section data-testid="admin-waivers" className="space-y-5">
        <Card p={16} style={{ borderColor: "#fecaca", background: "#fef2f2" }}>
          <div role="alert" data-testid="admin-waivers-error" className="text-sm text-red-800">
            Could not load waivers.
          </div>
        </Card>
      </section>
    );
  }

  if (waiversQuery.isPending) {
    return (
      <section data-testid="admin-waivers" className="space-y-6">
        <SummarySkeleton />
        <Card p={20}>
          <div className="h-5 w-44 rounded bg-neutral-100" />
          <div className="mt-5 space-y-3">
            <div className="h-4 w-full rounded bg-neutral-100" />
            <div className="h-4 w-5/6 rounded bg-neutral-100" />
            <div className="h-4 w-2/3 rounded bg-neutral-100" />
          </div>
        </Card>
      </section>
    );
  }

  const summary = waiversQuery.data.summary;
  const currentWaiver = waiversQuery.data.current_waiver ?? null;
  const waivers = waiversQuery.data.waivers ?? [];

  return (
    <section data-testid="admin-waivers" className="space-y-6">
      <SummaryCards summary={summary} />

      <LaneHeader index="01" title="Current waiver" />
      <CurrentWaiverCard waiver={currentWaiver} summary={summary} />

      <LaneHeader index="02" title="Per-student status" />
      <Card p={0}>
        {waivers.length === 0 ? (
          <p className="p-5 text-sm text-rally-subtle" data-testid="admin-waivers-empty">
            No waiver rows returned.
          </p>
        ) : (
          <WaiversTable waivers={waivers} />
        )}
      </Card>
    </section>
  );
}

function SummaryCards({ summary }: { summary: AdminWaiverSummary }) {
  return (
    <div className="grid gap-4 md:grid-cols-4">
      <Card p={20} accent="#10b981">
        <Overline>Signed current</Overline>
        <BigNum size={32}>{summary.signed_current}</BigNum>
        <p className="mt-1 text-[11px] text-rally-subtle">
          {formatPercent(summary.adoption_rate) ?? "Active waiver on file"}
        </p>
      </Card>
      <Card p={20} accent="#f59e0b">
        <Overline>Pending signature</Overline>
        <BigNum size={32}>{summary.pending_signature}</BigNum>
        <p className="mt-1 text-[11px] text-rally-subtle">Blocks first session</p>
      </Card>
      <Card p={20} accent="#facc15">
        <Overline>Expiring 30d</Overline>
        <BigNum size={32}>{summary.expiring_30d}</BigNum>
        <p className="mt-1 text-[11px] text-rally-subtle">Renewal attention needed</p>
      </Card>
      <Card p={20} accent="#94a3b8">
        <Overline>Outdated version</Overline>
        <BigNum size={32}>{summary.outdated_version}</BigNum>
        <p className="mt-1 text-[11px] text-rally-subtle">Previous waiver version</p>
      </Card>
    </div>
  );
}

function SummarySkeleton() {
  return (
    <div className="grid gap-4 md:grid-cols-4" aria-label="Loading waiver summary">
      {["signed", "pending", "expiring", "outdated"].map((key) => (
        <Card key={key} p={20}>
          <div className="h-3 w-24 rounded bg-neutral-100" />
          <div className="mt-3 h-8 w-14 rounded bg-neutral-100" />
          <div className="mt-3 h-3 w-28 rounded bg-neutral-100" />
        </Card>
      ))}
    </div>
  );
}

function CurrentWaiverCard({
  waiver,
  summary,
}: {
  waiver: AdminCurrentWaiverView | null;
  summary: AdminWaiverSummary;
}) {
  if (!waiver) {
    return (
      <Card p={20}>
        <p className="text-sm text-rally-subtle">Current waiver metadata is not available from the BFF yet.</p>
      </Card>
    );
  }

  const adoption =
    waiver.adoption_rate != null
      ? formatPercent(waiver.adoption_rate)
      : waiver.signed_count != null && waiver.total_count
        ? `${waiver.signed_count} / ${waiver.total_count}`
        : summary.active_students
          ? `${summary.signed_current} / ${summary.active_students}`
          : null;

  return (
    <div className="grid gap-4 lg:grid-cols-[1.35fr_0.65fr]">
      <Card p={24}>
        <div className="flex flex-col gap-5 sm:flex-row sm:items-start">
          <div className="relative flex h-[72px] w-14 shrink-0 flex-col items-center justify-center rounded-md bg-rally-ink px-2 text-center">
            <span className="absolute left-0 right-0 top-2 h-0.5 bg-rally-volt-400" />
            <span className="font-mono text-[9px] font-bold tracking-[0.15em] text-rally-volt-400">WAIVER</span>
            <span className="mt-1 font-display text-[22px] font-bold tracking-[-0.02em] text-white">
              {waiver.version}
            </span>
          </div>
          <div className="min-w-0 flex-1">
            <Overline>Active document</Overline>
            <h2 className="mt-1 font-display text-[22px] font-semibold tracking-[-0.02em] text-rally-ink">
              {waiver.title}
            </h2>
            {waiver.description && (
              <p className="mt-2 max-w-2xl text-[13px] leading-6 text-rally-muted">{waiver.description}</p>
            )}
            <dl className="mt-5 grid gap-4 border-t border-neutral-100 pt-4 sm:grid-cols-3">
              <MetaTerm label="Effective" value={formatDate(waiver.effective_at)} />
              <MetaTerm label="Last edited" value={formatDate(waiver.last_edited_at)} />
              <MetaTerm label="Adoption" value={adoption ?? "Not reported"} />
            </dl>
          </div>
        </div>
      </Card>

      <Card p={20}>
        <Overline>Version status</Overline>
        <div className="mt-4 space-y-3 text-sm">
          <div className="flex items-center justify-between gap-3">
            <span className="text-rally-muted">Current version</span>
            <span className="font-mono text-[12px] font-bold tracking-[0.05em] text-rally-ink">{waiver.version}</span>
          </div>
          <div className="flex items-center justify-between gap-3">
            <span className="text-rally-muted">Pending</span>
            <span className="font-mono text-[12px] font-bold tracking-[0.05em] text-rally-ink">
              {summary.pending_signature}
            </span>
          </div>
          <div className="flex items-center justify-between gap-3">
            <span className="text-rally-muted">Expiring soon</span>
            <span className="font-mono text-[12px] font-bold tracking-[0.05em] text-rally-ink">
              {summary.expiring_30d}
            </span>
          </div>
        </div>
      </Card>
    </div>
  );
}

function MetaTerm({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <Overline>{label}</Overline>
      <dd className="mt-1 font-mono text-[11px] font-semibold uppercase tracking-[0.08em] text-rally-ink">{value}</dd>
    </div>
  );
}

function WaiversTable({ waivers }: { waivers: AdminWaiverStudentRow[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[900px] text-sm">
        <thead>
          <tr className="border-b border-neutral-200 bg-neutral-50 text-left dark:border-neutral-800">
            <th className="px-5 py-3 font-mono text-[10px] font-bold uppercase tracking-overline text-rally-muted">Student and parent</th>
            <th className="px-3 py-3 font-mono text-[10px] font-bold uppercase tracking-overline text-rally-muted">Version</th>
            <th className="px-3 py-3 font-mono text-[10px] font-bold uppercase tracking-overline text-rally-muted">Signed</th>
            <th className="px-3 py-3 font-mono text-[10px] font-bold uppercase tracking-overline text-rally-muted">Method</th>
            <th className="px-3 py-3 font-mono text-[10px] font-bold uppercase tracking-overline text-rally-muted">Expires</th>
            <th className="px-5 py-3 font-mono text-[10px] font-bold uppercase tracking-overline text-rally-muted">Status</th>
          </tr>
        </thead>
        <tbody>
          {waivers.map((waiver) => (
            <tr
              key={waiver.waiver_id}
              data-testid={`admin-waivers-row-${waiver.waiver_id}`}
              className="border-b border-neutral-100 transition last:border-0 hover:bg-neutral-50 dark:border-neutral-800"
            >
              <td className="px-5 py-4">
                <div className="flex items-center gap-3">
                  <Avatar name={waiver.student_name} size={34} />
                  <div>
                    <div className="font-semibold text-rally-base">{waiver.student_name}</div>
                    <div className="text-[12px] text-rally-subtle">
                      {waiver.parent_name || waiver.parent_email || waiver.parent_id}
                    </div>
                  </div>
                </div>
              </td>
              <td className="px-3 py-4 font-mono text-[12px] font-bold tracking-[0.05em] text-rally-ink">
                {waiver.version ?? "-"}
              </td>
              <td className="px-3 py-4 font-mono text-[11px] font-semibold uppercase tracking-[0.05em] text-rally-muted">
                {formatDate(waiver.signed_at)}
              </td>
              <td className="px-3 py-4 text-[12px] text-rally-muted">{waiver.method ?? "-"}</td>
              <td className="px-3 py-4 font-mono text-[11px] font-semibold uppercase tracking-[0.05em] text-rally-muted">
                {formatDate(waiver.expires_at)}
              </td>
              <td className="px-5 py-4">
                <Chip variant={chipForStatus(waiver.status)} label={labelForStatus(waiver.status)} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function chipForStatus(status: AdminWaiverStatus) {
  if (status === "signed") return "enrolled";
  if (status === "pending") return "pending";
  if (status === "expiring") return "pending";
  return "paused";
}

function labelForStatus(status: AdminWaiverStatus) {
  if (status === "signed") return "SIGNED";
  if (status === "pending") return "PENDING";
  if (status === "expiring") return "EXPIRING";
  return "OUTDATED";
}

function formatDate(value: string | null | undefined): string {
  if (!value) return "-";
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "2-digit",
    year: "numeric",
  }).format(new Date(value));
}

function formatPercent(value: number | null | undefined): string | null {
  if (value == null) return null;
  return `${Math.round(value * 100)}% of active students`;
}
