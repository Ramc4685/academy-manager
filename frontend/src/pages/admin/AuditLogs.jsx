import { useEffect, useState } from "react";
import { api, formatDateTime } from "../../lib/api";

export default function AdminAuditLogs() {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.get("/audit-logs?limit=500").then((r) => setItems(r.data)).finally(() => setLoading(false));
  }, []);

  return (
    <div className="space-y-6" data-testid="admin-audit-logs">
      <div>
        <h1 className="text-3xl md:text-4xl font-display font-bold tracking-tighter text-slate-900">Audit Logs</h1>
        <p className="text-sm text-slate-600 mt-1">Latest 500 actions across the system</p>
      </div>
      <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-slate-50">
            <tr className="text-left text-xs uppercase tracking-[0.1em] text-slate-500">
              <th className="px-4 py-3">Time</th><th className="px-4 py-3">User</th>
              <th className="px-4 py-3">Action</th><th className="px-4 py-3">Entity</th>
              <th className="px-4 py-3">Summary</th>
            </tr>
          </thead>
          <tbody>
            {loading && <tr><td colSpan={5} className="py-10 text-center text-slate-500">Loading…</td></tr>}
            {!loading && items.length === 0 && <tr><td colSpan={5} className="py-10 text-center text-slate-500">No audit entries yet.</td></tr>}
            {items.map((a, i) => (
              <tr key={i} className="border-b border-slate-100 hover:bg-slate-50">
                <td className="px-4 py-3 text-xs text-slate-600 whitespace-nowrap">{formatDateTime(a.created_at)}</td>
                <td className="px-4 py-3">
                  <div className="text-slate-900">{a.user_email}</div>
                  <div className="text-xs text-slate-500 capitalize">{a.role}</div>
                </td>
                <td className="px-4 py-3"><span className="px-2 py-0.5 rounded-full bg-blue-50 text-blue-700 text-xs font-medium capitalize">{a.action.replace(/_/g, " ")}</span></td>
                <td className="px-4 py-3 capitalize text-slate-700">{a.entity_type}</td>
                <td className="px-4 py-3 text-slate-700">{a.summary}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
