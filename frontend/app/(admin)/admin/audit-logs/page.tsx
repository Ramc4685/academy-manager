"use client";

import { useQuery } from "@tanstack/react-query";

import { listAuditLogs } from "@/lib/api/admin";

export default function AdminAuditLogsPage() {
  const { data, isLoading, isError } = useQuery({
    queryKey: ["admin", "audit-logs"],
    queryFn: listAuditLogs,
  });

  const logs = data?.logs ?? [];

  return (
    <section data-testid="admin-audit-logs" className="space-y-5">
      <div>
        <h1 className="text-2xl font-semibold">Audit logs</h1>
        <p className="mt-1 text-sm text-neutral-500">
          Recent operational events from the v2 admin BFF.
        </p>
      </div>

      {isError ? (
        <p role="alert" className="rounded-md bg-red-50 p-3 text-sm text-red-700">
          Could not load audit logs.
        </p>
      ) : isLoading ? (
        <Skeleton />
      ) : logs.length === 0 ? (
        <p className="text-sm text-neutral-500">No audit events recorded yet.</p>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-neutral-200 bg-white dark:border-neutral-800 dark:bg-neutral-900">
          <table className="w-full min-w-[760px] text-sm">
            <thead>
              <tr className="border-b border-neutral-200 text-left text-neutral-500 dark:border-neutral-800">
                <th className="px-4 py-3 font-medium">Event</th>
                <th className="px-4 py-3 font-medium">Actor</th>
                <th className="px-4 py-3 font-medium">Entity</th>
                <th className="px-4 py-3 font-medium">Time</th>
              </tr>
            </thead>
            <tbody>
              {logs.map((log) => (
                <tr key={log.audit_id} className="border-b border-neutral-100 last:border-0 dark:border-neutral-800">
                  <td className="px-4 py-3">
                    <div className="font-medium">{log.action}</div>
                    <div className="font-mono text-xs text-neutral-500">{log.audit_id}</div>
                  </td>
                  <td className="px-4 py-3 font-mono text-xs text-neutral-500">
                    {log.actor_id ?? "-"}
                  </td>
                  <td className="px-4 py-3 text-neutral-600 dark:text-neutral-300">
                    {log.entity_type ?? "-"}
                    {log.entity_id ? <span className="ml-2 font-mono text-xs">{log.entity_id}</span> : null}
                  </td>
                  <td className="px-4 py-3 text-neutral-600 dark:text-neutral-300">
                    {new Date(log.created_at).toLocaleString()}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function Skeleton() {
  return (
    <div className="space-y-2">
      {[0, 1, 2].map((i) => (
        <div key={i} className="h-14 animate-pulse rounded-lg bg-neutral-100 dark:bg-neutral-800" />
      ))}
    </div>
  );
}
