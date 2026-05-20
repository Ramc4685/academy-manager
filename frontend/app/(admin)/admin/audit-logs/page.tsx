"use client";

import { useQuery } from "@tanstack/react-query";

import { listAuditLogs } from "@/lib/api/admin";
import { Card } from "@/components/ds/card";
import { Chip, type ChipVariant, CHIP_VARIANTS } from "@/components/ds/chip";
import { Avatar } from "@/components/ds/avatar";
import { LaneHeader } from "@/components/ds/lane";

function getActionVariant(action: string): ChipVariant {
  const normalized = action.toLowerCase();
  if (normalized.includes("create") || normalized.includes("add")) return "open";
  if (normalized.includes("update") || normalized.includes("edit")) return "approval";
  if (normalized.includes("delete") || normalized.includes("remove")) return "failed";
  if (normalized.includes("pause")) return "paused";
  if (normalized.includes("resume")) return "enrolled";
  if (normalized.includes("approve")) return "approved";
  if (normalized.includes("cancel")) return "closing";
  if (normalized.includes("waitlist")) return "waitlist";
  if (normalized.includes("transfer")) return "transferred";
  
  const exactMatch = Object.keys(CHIP_VARIANTS).includes(normalized) ? (normalized as ChipVariant) : null;
  if (exactMatch) return exactMatch;
  return "manual";
}

export default function AdminAuditLogsPage() {
  const { data, isLoading, isError } = useQuery({
    queryKey: ["admin", "audit-logs"],
    queryFn: listAuditLogs,
  });

  const logs = data?.logs ?? [];

  return (
    <section data-testid="admin-audit-logs" className="space-y-6">
      <div>
        <LaneHeader title="Audit Logs" />
        <p className="mt-1 text-sm text-slate-500">
          Recent operational events from the v2 admin BFF.
        </p>
      </div>

      {isError ? (
        <Card p={16} accent="#ef4444" className="bg-red-50/50">
          <p role="alert" className="text-sm font-medium text-red-800">
            Could not load audit logs.
          </p>
        </Card>
      ) : isLoading ? (
        <Skeleton />
      ) : logs.length === 0 ? (
        <Card p={24}>
          <p className="text-sm text-slate-500 text-center py-8" data-testid="admin-audit-logs-empty">
            No audit events recorded yet.
          </p>
        </Card>
      ) : (
        <Card p={0} className="overflow-x-auto">
          <table className="w-full text-left text-sm whitespace-nowrap">
            <thead>
              <tr className="border-b border-slate-200 bg-slate-50/50 dark:border-slate-800 dark:bg-slate-800/50">
                <th className="px-5 py-3 font-medium text-slate-500">Timestamp</th>
                <th className="px-5 py-3 font-medium text-slate-500">Actor</th>
                <th className="px-5 py-3 font-medium text-slate-500">Action</th>
                <th className="px-5 py-3 font-medium text-slate-500">Entity</th>
              </tr>
            </thead>
            <tbody>
              {logs.map((log) => {
                const actionVariant = getActionVariant(log.action);
                const actorName = log.actor_id ?? "System";
                return (
                  <tr 
                    key={log.audit_id} 
                    data-testid={`admin-audit-logs-row-${log.audit_id}`} 
                    className="border-b border-slate-100 last:border-0 hover:bg-slate-50/50 dark:border-slate-800 dark:hover:bg-slate-800/50"
                  >
                    <td className="px-5 py-4 font-mono text-[13px] text-slate-600 dark:text-slate-300">
                      {new Date(log.created_at).toLocaleString()}
                    </td>
                    <td className="px-5 py-4">
                      <div className="flex items-center gap-3">
                        <Avatar name={actorName} size={28} />
                        <span className="font-medium text-slate-700 dark:text-slate-200">
                          {actorName}
                        </span>
                      </div>
                    </td>
                    <td className="px-5 py-4">
                      <Chip variant={actionVariant} label={log.action.toUpperCase()} />
                    </td>
                    <td className="px-5 py-4">
                      <div className="flex items-center gap-2">
                        <span className="text-slate-600 dark:text-slate-400">
                          {log.entity_type ?? "unknown"}
                        </span>
                        {log.entity_id ? (
                          <span className="font-mono text-[13px] text-slate-400 dark:text-slate-500">
                            {log.entity_id}
                          </span>
                        ) : null}
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </Card>
      )}
    </section>
  );
}

function Skeleton() {
  return (
    <Card p={0}>
      <div className="divide-y divide-slate-100 dark:divide-slate-800">
        {[0, 1, 2, 3, 4].map((i) => (
          <div key={i} className="p-4 flex items-center gap-4">
            <div className="h-4 w-32 animate-pulse rounded bg-slate-100 dark:bg-slate-800" />
            <div className="h-8 w-8 animate-pulse rounded-full bg-slate-100 dark:bg-slate-800" />
            <div className="h-4 w-24 animate-pulse rounded bg-slate-100 dark:bg-slate-800" />
            <div className="h-6 w-16 animate-pulse rounded bg-slate-100 dark:bg-slate-800" />
            <div className="h-4 w-24 animate-pulse rounded bg-slate-100 dark:bg-slate-800" />
          </div>
        ))}
      </div>
    </Card>
  );
}
