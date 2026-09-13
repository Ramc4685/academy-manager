"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { listAuditLogs, type AdminAuditActorType } from "@/lib/api/admin";
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

const ACTOR_TYPE_FILTERS: { value: AdminAuditActorType | null; label: string }[] = [
  { value: null, label: "Everyone" },
  { value: "owner", label: "Owners" },
  { value: "admin", label: "Admins" },
  { value: "coach", label: "Coaches" },
  { value: "parent", label: "Parents" },
  { value: "system", label: "System" },
];

function getActorVariant(actorType: AdminAuditActorType | null): ChipVariant {
  if (actorType === "system") return "manual";
  if (actorType === "owner" || actorType === "admin") return "approval";
  if (actorType === "coach") return "enrolled";
  if (actorType === "parent") return "open";
  return "manual";
}

function formatActorType(actorType: AdminAuditActorType | null) {
  if (!actorType) return "Unknown";
  return actorType.charAt(0).toUpperCase() + actorType.slice(1);
}

export default function AdminAuditLogsPage() {
  const [actorType, setActorType] = useState<AdminAuditActorType | null>(null);

  const { data, isLoading, isError } = useQuery({
    queryKey: ["admin", "audit-logs", actorType],
    queryFn: () => listAuditLogs(actorType),
  });

  const logs = data?.logs ?? [];

  return (
    <section data-testid="admin-audit-logs" className="space-y-6">
      <LaneHeader index="01" title="Operational audit trail" />

      <div className="flex flex-wrap gap-2" role="group" aria-label="Filter by actor type">
        {ACTOR_TYPE_FILTERS.map((filter) => {
          const active = filter.value === actorType;
          return (
            <button
              key={filter.label}
              type="button"
              data-testid={`admin-audit-logs-filter-${filter.value ?? "all"}`}
              aria-pressed={active}
              onClick={() => setActorType(filter.value)}
              className={`rounded-full border px-3 py-1 font-mono text-[11px] uppercase tracking-overline transition-colors ${
                active
                  ? "border-slate-900 bg-slate-900 text-white dark:border-slate-100 dark:bg-slate-100 dark:text-slate-900"
                  : "border-slate-200 text-rally-muted hover:bg-slate-50 dark:border-slate-700 dark:hover:bg-slate-800"
              }`}
            >
              {filter.label}
            </button>
          );
        })}
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
            {actorType ? "No audit events for this kind of actor." : "No audit events recorded yet."}
          </p>
        </Card>
      ) : (
        <Card p={0} className="overflow-x-auto">
          <table className="w-full text-left text-sm whitespace-nowrap">
            <thead>
              <tr className="border-b border-slate-200 bg-slate-50/50 dark:border-slate-800 dark:bg-slate-800/50">
                <th className="px-5 py-3 font-mono text-[10px] font-bold uppercase tracking-overline text-rally-muted">Timestamp</th>
                <th className="px-5 py-3 font-mono text-[10px] font-bold uppercase tracking-overline text-rally-muted">Actor</th>
                <th className="px-5 py-3 font-mono text-[10px] font-bold uppercase tracking-overline text-rally-muted">Action</th>
                <th className="px-5 py-3 font-mono text-[10px] font-bold uppercase tracking-overline text-rally-muted">Entity</th>
              </tr>
            </thead>
            <tbody>
              {logs.map((log) => {
                const actionVariant = getActionVariant(log.action);
                const actorName =
                  log.actor_name ?? (log.actor_id ? "Unknown actor" : "System event");
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
                        <div>
                          <div className="font-medium text-slate-700 dark:text-slate-200">
                            {actorName}
                          </div>
                          <div className="mt-1 flex items-center gap-2">
                            <Chip
                              variant={getActorVariant(log.actor_type)}
                              label={log.actor_role ?? formatActorType(log.actor_type)}
                            />
                          </div>
                          {log.actor_id ? (
                            <div className="font-mono text-[11px] text-slate-400">
                              Support ref {log.actor_id}
                            </div>
                          ) : null}
                        </div>
                      </div>
                    </td>
                    <td className="px-5 py-4">
                      <Chip variant={actionVariant} label={formatActionLabel(log.action)} />
                    </td>
                    <td className="px-5 py-4">
                      <div>
                        <div className="font-medium text-slate-600 dark:text-slate-400">
                          {formatEntityType(log.entity_type)}
                        </div>
                        {log.entity_id ? (
                          <div className="font-mono text-[11px] text-slate-400 dark:text-slate-500">
                            Support ref {log.entity_id}
                          </div>
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

function formatActionLabel(action: string) {
  return action
    .replace(/[._-]+/g, " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function formatEntityType(entityType: string | null) {
  if (!entityType) return "System";
  return entityType
    .replace(/[._-]+/g, " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
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
