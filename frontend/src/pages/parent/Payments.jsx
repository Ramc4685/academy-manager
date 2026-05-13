import { useEffect, useState } from "react";
import { api, currency, formatDate } from "../../lib/api";
import StatusBadge from "../../components/StatusBadge";

export default function ParentPayments() {
  const [items, setItems] = useState([]);
  useEffect(() => { api.get("/payments").then((r) => setItems(r.data)); }, []);

  const totalDue = items.filter((p) => p.status === "pending").reduce((s, p) => s + p.final_amount, 0);

  return (
    <div className="space-y-6" data-testid="parent-payments">
      <div>
        <h1 className="text-3xl md:text-4xl font-display font-bold tracking-tighter text-slate-900">Payments</h1>
        <p className="text-sm text-slate-600 mt-1">Outstanding balance: <span className="font-semibold text-blue-600">{currency(totalDue)}</span></p>
      </div>
      <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-slate-50">
            <tr className="text-left text-xs uppercase tracking-[0.1em] text-slate-500">
              <th className="px-4 py-3">Period</th><th className="px-4 py-3">Student</th><th className="px-4 py-3">Session</th>
              <th className="px-4 py-3 text-right">Amount</th><th className="px-4 py-3">Status</th><th className="px-4 py-3">Paid on</th>
            </tr>
          </thead>
          <tbody>
            {items.length === 0 && <tr><td colSpan={6} className="py-10 text-center text-slate-500">No payments yet.</td></tr>}
            {items.map((p) => (
              <tr key={p.id} className="border-b border-slate-100 hover:bg-slate-50">
                <td className="px-4 py-3 font-mono text-xs">{p.period}</td>
                <td className="px-4 py-3 font-medium text-slate-900">{p.student_name}</td>
                <td className="px-4 py-3 text-slate-700">{p.session_name}</td>
                <td className="px-4 py-3 text-right font-semibold text-blue-600">{currency(p.final_amount)}</td>
                <td className="px-4 py-3"><StatusBadge status={p.status} /></td>
                <td className="px-4 py-3 text-xs text-slate-500">{p.payment_date ? formatDate(p.payment_date) : "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="text-xs text-slate-500">Payments are tracked manually by the academy. Please pay at the front desk and your status will update shortly.</div>
    </div>
  );
}
