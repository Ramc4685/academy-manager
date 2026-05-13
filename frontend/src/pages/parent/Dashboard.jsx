import { useEffect, useState } from "react";
import { api, currency, formatDate } from "../../lib/api";
import KPICard from "../../components/KPICard";
import { Link } from "react-router-dom";

export default function ParentDashboard() {
  const [data, setData] = useState(null);
  useEffect(() => { api.get("/dashboard/parent").then((r) => setData(r.data)); }, []);

  if (!data) return <div className="text-slate-500 text-sm">Loading…</div>;
  const k = data.kpis;

  return (
    <div className="space-y-8" data-testid="parent-dashboard">
      <div>
        <h1 className="text-3xl md:text-4xl font-display font-bold tracking-tighter text-slate-900">Parent Portal</h1>
        <p className="text-sm text-slate-600 mt-1">Manage your children, payments, and schedule</p>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
        <KPICard testId="parent-kpi-children" label="Children" value={k.children} accent="blue" />
        <KPICard testId="parent-kpi-enrollments" label="Active enrollments" value={k.active_enrollments} accent="slate" />
        <KPICard testId="parent-kpi-pending" label="Pending payments" value={k.pending_count} hint={currency(k.pending_total)} accent="yellow" />
        <div className="bg-white border border-slate-200 rounded-xl p-6 shadow-sm">
          <div className="text-xs font-bold uppercase tracking-[0.18em] text-slate-500">Quick actions</div>
          <div className="mt-3 space-y-2">
            <Link to="/parent/children" className="block text-sm text-blue-600 hover:underline">+ Add child</Link>
            <Link to="/parent/payments" className="block text-sm text-blue-600 hover:underline">View payments</Link>
          </div>
        </div>
      </div>

      <div className="bg-white border border-slate-200 rounded-xl p-6">
        <h3 className="text-lg font-display font-semibold tracking-tight text-slate-900">Upcoming classes</h3>
        <div className="mt-4 space-y-2" data-testid="parent-upcoming">
          {data.upcoming.length === 0 && <div className="text-sm text-slate-500">No classes scheduled in the next 7 days.</div>}
          {data.upcoming.map((u, i) => (
            <div key={i} className="flex justify-between items-center p-3 rounded-lg border border-slate-100 hover:bg-slate-50">
              <div>
                <div className="font-medium text-slate-900 text-sm">{u.session_name}</div>
                <div className="text-xs text-slate-500">{formatDate(u.date)} · {u.start_time}–{u.end_time}</div>
              </div>
              <span className="text-xs text-slate-500">{u.location}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
