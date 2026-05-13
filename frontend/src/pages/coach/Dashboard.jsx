import { useEffect, useState } from "react";
import { api, currency, formatDate } from "../../lib/api";
import KPICard from "../../components/KPICard";
import StatusBadge from "../../components/StatusBadge";
import { Link } from "react-router-dom";

export default function CoachDashboard() {
  const [data, setData] = useState(null);

  useEffect(() => { api.get("/dashboard/coach").then((r) => setData(r.data)); }, []);

  if (!data) return <div className="text-slate-500 text-sm">Loading…</div>;
  const k = data.kpis;

  return (
    <div className="space-y-8" data-testid="coach-dashboard">
      <div>
        <h1 className="text-3xl md:text-4xl font-display font-bold tracking-tighter text-slate-900">Coach Dashboard</h1>
        <p className="text-sm text-slate-600 mt-1">Your sessions, students, and current month payout</p>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
        <KPICard testId="coach-kpi-sessions" label="Sessions assigned" value={k.sessions_count} accent="blue" />
        <KPICard testId="coach-kpi-students" label="Students" value={k.students_count} accent="slate" />
        <KPICard testId="coach-kpi-payout" label="Current payout" value={currency(k.current_payout)} accent="yellow" />
        <div className="bg-white border border-slate-200 rounded-xl p-6 shadow-sm">
          <div className="text-xs font-bold uppercase tracking-[0.18em] text-slate-500">Payout status</div>
          <div className="mt-3"><StatusBadge status={k.payout_status} /></div>
          <div className="text-xs text-slate-500 mt-2">Admin must approve before payout is paid</div>
        </div>
      </div>

      <div className="bg-white border border-slate-200 rounded-xl p-6">
        <div className="flex justify-between items-center mb-4">
          <h3 className="text-lg font-display font-semibold tracking-tight text-slate-900">Upcoming classes</h3>
          <Link to="/coach/sessions" className="text-sm text-blue-600 hover:underline">View all sessions</Link>
        </div>
        <div className="space-y-2" data-testid="coach-upcoming">
          {data.upcoming.length === 0 && <div className="text-sm text-slate-500">No upcoming classes.</div>}
          {data.upcoming.map((u, i) => (
            <Link key={i} to={`/coach/sessions/${u.session_id}`} className="block p-3 rounded-lg border border-slate-100 hover:bg-slate-50">
              <div className="flex justify-between">
                <div>
                  <div className="font-medium text-slate-900 text-sm">{u.name}</div>
                  <div className="text-xs text-slate-500">{formatDate(u.date)} · {u.start_time}–{u.end_time}</div>
                </div>
                <span className="text-xs text-slate-500">{u.location}</span>
              </div>
            </Link>
          ))}
        </div>
      </div>
    </div>
  );
}
