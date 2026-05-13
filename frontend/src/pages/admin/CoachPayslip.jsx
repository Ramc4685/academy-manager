import { useEffect, useState } from "react";
import { api, currency, currentPeriod } from "../../lib/api";
import { Input } from "../../components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "../../components/ui/select";
import StatusBadge from "../../components/StatusBadge";

export default function CoachPayslip() {
  const [coaches, setCoaches] = useState([]);
  const [coachId, setCoachId] = useState("");
  const [period, setPeriod] = useState(currentPeriod());
  const [data, setData] = useState(null);

  useEffect(() => {
    api.get("/users?role=coach").then((r) => {
      setCoaches(r.data);
      if (r.data.length && !coachId) setCoachId(r.data[0].id);
    });
  }, []); // eslint-disable-line

  useEffect(() => {
    if (!coachId || !period) return;
    api.get(`/coach-payouts/${coachId}/payslip?period=${period}`).then((r) => setData(r.data));
  }, [coachId, period]);

  return (
    <div className="space-y-6" data-testid="admin-payslip">
      <div className="flex items-end justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-3xl md:text-4xl font-display font-bold tracking-tighter text-slate-900">Coach Payslip</h1>
          <p className="text-sm text-slate-600 mt-1">Per-coach × month breakdown of enrolled kids and payout</p>
        </div>
        <div className="flex gap-2">
          <Select value={coachId} onValueChange={setCoachId}>
            <SelectTrigger className="w-48" data-testid="payslip-coach"><SelectValue placeholder="Select coach" /></SelectTrigger>
            <SelectContent>{coaches.map((c) => <SelectItem key={c.id} value={c.id}>{c.name || c.email}</SelectItem>)}</SelectContent>
          </Select>
          <Input type="month" value={period} onChange={(e) => setPeriod(e.target.value)} className="w-44" data-testid="payslip-period" />
        </div>
      </div>

      {!data && <div className="text-slate-500 text-sm">Select a coach and period.</div>}
      {data && (
        <>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-5 gap-6">
            <div className="bg-white border border-slate-200 rounded-xl p-6">
              <div className="text-xs uppercase tracking-[0.18em] text-slate-500 font-bold">Coach</div>
              <div className="mt-2 text-xl font-display font-bold text-slate-900">{data.coach_name}</div>
            </div>
            <div className="bg-white border border-slate-200 rounded-xl p-6">
              <div className="text-xs uppercase tracking-[0.18em] text-slate-500 font-bold">Kids enrolled</div>
              <div className="mt-2 text-3xl font-display font-bold text-blue-600">{data.kids_enrolled}</div>
            </div>
            <div className="bg-white border border-slate-200 rounded-xl p-6">
              <div className="text-xs uppercase tracking-[0.18em] text-slate-500 font-bold">Expected revenue</div>
              <div className="mt-2 text-3xl font-display font-bold text-slate-900">{currency(data.expected_revenue)}</div>
              <div className="text-xs text-slate-500 mt-1">If everyone pays</div>
            </div>
            <div className="bg-white border border-slate-200 rounded-xl p-6">
              <div className="text-xs uppercase tracking-[0.18em] text-slate-500 font-bold">Collected so far</div>
              <div className="mt-2 text-3xl font-display font-bold text-emerald-600">{currency(data.collected_revenue ?? 0)}</div>
              <div className="text-xs text-slate-500 mt-1">Actually received</div>
            </div>
            <div className="bg-white border border-slate-200 rounded-xl p-6">
              <div className="text-xs uppercase tracking-[0.18em] text-slate-500 font-bold">Payout</div>
              <div className="mt-2 text-3xl font-display font-bold text-yellow-700">{currency(data.payout_amount)}</div>
              <div className="mt-1 text-xs text-slate-500">
                {data.rule_type === "revenue_percentage" && (
                  <>= {currency(data.collected_revenue ?? 0)} × {data.rule_value}%</>
                )}
                {data.rule_type !== "revenue_percentage" && (
                  <>{data.rule_type?.replace(/_/g, " ")} @ {data.rule_value}</>
                )}
              </div>
              <div className="mt-2"><StatusBadge status={data.current_status} /></div>
            </div>
          </div>

          <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
            <table className="w-full text-sm">
              <thead className="bg-slate-50">
                <tr className="text-left text-xs uppercase tracking-[0.1em] text-slate-500">
                  <th className="px-4 py-3">Child</th><th className="px-4 py-3">Session</th><th className="px-4 py-3">Skill</th>
                  <th className="px-4 py-3">Billing</th><th className="px-4 py-3 text-right">Price</th><th className="px-4 py-3">Payment</th>
                </tr>
              </thead>
              <tbody>
                {data.rows.length === 0 && <tr><td colSpan={6} className="py-10 text-center text-slate-500">No kids enrolled this month.</td></tr>}
                {data.rows.map((r, i) => (
                  <tr key={i} className="border-b border-slate-100 hover:bg-slate-50">
                    <td className="px-4 py-3 font-medium text-slate-900">{r.child}</td>
                    <td className="px-4 py-3 text-slate-700 text-xs">{r.session}</td>
                    <td className="px-4 py-3 capitalize">{r.skill}</td>
                    <td className="px-4 py-3"><StatusBadge status={r.billing_type === "Standard" ? "active" : (r.billing_type === "NoCharge" ? "excused" : "pending")} /></td>
                    <td className="px-4 py-3 text-right font-semibold">{currency(r.price)}</td>
                    <td className="px-4 py-3"><StatusBadge status={r.payment_status} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}
