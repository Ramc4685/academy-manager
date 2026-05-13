import { useEffect, useState } from "react";
import { api } from "../../lib/api";
import { currency, formatDate, currentPeriod } from "../../lib/api";
import KPICard from "../../components/KPICard";
import StatusBadge from "../../components/StatusBadge";
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, Legend } from "recharts";

export default function AdminDashboard() {
  const [period, setPeriod] = useState(currentPeriod());
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    api.get(`/dashboard/admin?period=${period}`).then((r) => setData(r.data)).finally(() => setLoading(false));
  }, [period]);

  if (loading || !data) {
    return (
      <div className="space-y-6" data-testid="admin-dashboard-loading">
        <div className="h-8 bg-slate-200 rounded animate-pulse w-1/3" />
        <div className="grid grid-cols-1 md:grid-cols-4 gap-6">
          {[1, 2, 3, 4].map((i) => (<div key={i} className="h-32 bg-slate-200 rounded-xl animate-pulse" />))}
        </div>
      </div>
    );
  }

  const k = data.kpis;

  return (
    <div className="space-y-8" data-testid="admin-dashboard">
      <div className="flex items-end justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-3xl md:text-4xl font-display font-bold tracking-tighter text-slate-900">Academy Dashboard</h1>
          <p className="text-sm text-slate-600 mt-1">Financial and operational overview · Period {period}</p>
        </div>
        <input
          type="month"
          value={period}
          onChange={(e) => setPeriod(e.target.value)}
          data-testid="period-picker"
          className="px-3 py-2 border border-slate-200 rounded-lg bg-white text-sm text-slate-700"
        />
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
        <KPICard testId="kpi-income" label="Collected" value={currency(k.collected_revenue ?? k.monthly_income)} hint={`of ${currency(k.expected_revenue ?? k.monthly_income)} expected`} accent="blue" />
        <KPICard testId="kpi-expenses" label="Expenses" value={currency(k.expenses)} hint="Excl. coach payouts" accent="slate" />
        <KPICard testId="kpi-payouts" label="Coach Payouts" value={currency(k.coach_payouts)} hint="Calculated" accent="yellow" />
        <KPICard testId="kpi-profit" label="Net Profit" value={currency(k.net_profit)} hint="Collected − expenses − payouts" accent={k.net_profit >= 0 ? "emerald" : "red"} />
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
        <KPICard testId="kpi-students" label="Students" value={k.students} hint="Active" accent="slate" />
        <KPICard testId="kpi-sessions" label="Active Sessions" value={k.active_sessions} hint="" accent="slate" />
        <KPICard testId="kpi-pending" label="Pending Payments" value={k.pending_count} hint={`${currency(k.pending_total)} due`} accent="yellow" />
        <KPICard testId="kpi-waived" label="Waived / No Charge" value={currency(k.waived_value ?? 0)} hint="Free students value" accent="slate" />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-5 gap-6">
        <div className="lg:col-span-3 bg-white border border-slate-200 rounded-xl p-6">
          <h3 className="text-lg font-display font-semibold tracking-tight text-slate-900">Profit Trend (last 6 months)</h3>
          <div className="mt-4 h-72">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={data.trend}>
                <CartesianGrid strokeDasharray="3 3" stroke="#E2E8F0" />
                <XAxis dataKey="period" stroke="#64748B" fontSize={12} />
                <YAxis stroke="#64748B" fontSize={12} />
                <Tooltip contentStyle={{ borderRadius: 8, border: "1px solid #E2E8F0" }} />
                <Legend />
                <Line type="monotone" dataKey="revenue" stroke="#2563EB" strokeWidth={2} dot={false} />
                <Line type="monotone" dataKey="expenses" stroke="#0F172A" strokeWidth={2} dot={false} />
                <Line type="monotone" dataKey="profit" stroke="#FACC15" strokeWidth={2.5} dot={{ r: 3 }} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>
        <div className="lg:col-span-2 bg-white border border-slate-200 rounded-xl p-6">
          <h3 className="text-lg font-display font-semibold tracking-tight text-slate-900">Upcoming Classes</h3>
          <div className="mt-4 space-y-3 max-h-72 overflow-y-auto" data-testid="upcoming-classes">
            {data.upcoming.length === 0 && <div className="text-sm text-slate-500">No upcoming classes in the next 7 days.</div>}
            {data.upcoming.map((u, i) => (
              <div key={i} className="flex items-center justify-between p-3 rounded-lg border border-slate-100 hover:bg-slate-50">
                <div>
                  <div className="font-medium text-slate-900 text-sm">{u.name}</div>
                  <div className="text-xs text-slate-500">{formatDate(u.date)} · {u.start_time}–{u.end_time}</div>
                </div>
                <span className="text-xs text-slate-500">{u.location}</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      <div className="bg-white border border-slate-200 rounded-xl p-6">
        <h3 className="text-lg font-display font-semibold tracking-tight text-slate-900">Session Profitability & Utilization</h3>
        <table className="w-full mt-4 text-sm" data-testid="session-profitability">
          <thead>
            <tr className="text-left text-xs uppercase tracking-[0.1em] text-slate-500">
              <th className="py-2">Session</th><th className="py-2">Enrolled</th><th className="py-2">Utilization</th><th className="py-2 text-right">Revenue</th>
            </tr>
          </thead>
          <tbody>
            {data.session_profitability.length === 0 && (
              <tr><td colSpan={4} className="py-6 text-center text-slate-500">No sessions yet.</td></tr>
            )}
            {data.session_profitability.map((s) => (
              <tr key={s.id} className="border-b border-slate-100 hover:bg-slate-50">
                <td className="py-3 font-medium text-slate-900">{s.name}</td>
                <td className="py-3 text-slate-700">{s.enrolled}/{s.capacity || "-"}</td>
                <td className="py-3">
                  <div className="flex items-center gap-2">
                    <div className="w-24 h-1.5 bg-slate-100 rounded-full overflow-hidden">
                      <div className={`h-full ${s.utilization >= 80 ? "bg-emerald-500" : s.utilization >= 50 ? "bg-blue-500" : "bg-amber-500"}`} style={{ width: `${Math.min(100, s.utilization || 0)}%` }} />
                    </div>
                    <span className="text-xs text-slate-700 font-medium">{s.utilization || 0}%</span>
                  </div>
                </td>
                <td className="py-3 text-right font-semibold text-blue-600">{currency(s.revenue)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
