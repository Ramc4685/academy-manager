import { useEffect, useState } from "react";
import { api, formatDate } from "../../lib/api";
import StatusBadge from "../../components/StatusBadge";

export default function ParentAttendance() {
  const [items, setItems] = useState([]);
  useEffect(() => { api.get("/attendance").then((r) => setItems(r.data)); }, []);

  return (
    <div className="space-y-6" data-testid="parent-attendance">
      <div>
        <h1 className="text-3xl md:text-4xl font-display font-bold tracking-tighter text-slate-900">Attendance</h1>
        <p className="text-sm text-slate-600 mt-1">Recent attendance for your children</p>
      </div>
      <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-slate-50">
            <tr className="text-left text-xs uppercase tracking-[0.1em] text-slate-500">
              <th className="px-4 py-3">Date</th><th className="px-4 py-3">Student</th>
              <th className="px-4 py-3">Status</th><th className="px-4 py-3">Notes</th>
            </tr>
          </thead>
          <tbody>
            {items.length === 0 && <tr><td colSpan={4} className="py-10 text-center text-slate-500">No attendance records yet.</td></tr>}
            {items.map((a) => (
              <tr key={a.id} className="border-b border-slate-100 hover:bg-slate-50">
                <td className="px-4 py-3 text-slate-700">{formatDate(a.date)}</td>
                <td className="px-4 py-3 font-medium text-slate-900">{a.student_name}</td>
                <td className="px-4 py-3"><StatusBadge status={a.status} /></td>
                <td className="px-4 py-3 text-xs text-slate-500">{a.notes || "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
