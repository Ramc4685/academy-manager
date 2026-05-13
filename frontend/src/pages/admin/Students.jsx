import { useEffect, useState } from "react";
import { api, formatApiError, formatDate } from "../../lib/api";
import StatusBadge from "../../components/StatusBadge";
import { Input } from "../../components/ui/input";

export default function AdminStudents() {
  const [items, setItems] = useState([]);
  const [filter, setFilter] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.get("/students").then((r) => setItems(r.data)).finally(() => setLoading(false));
  }, []);

  const filtered = items.filter((s) => {
    if (!filter) return true;
    const t = `${s.first_name} ${s.last_name} ${s.parent?.email || ""}`.toLowerCase();
    return t.includes(filter.toLowerCase());
  });

  return (
    <div className="space-y-6" data-testid="admin-students">
      <div className="flex items-end justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-3xl md:text-4xl font-display font-bold tracking-tighter text-slate-900">Students</h1>
          <p className="text-sm text-slate-600 mt-1">All registered students</p>
        </div>
        <Input placeholder="Search by name or parent…" value={filter} onChange={(e) => setFilter(e.target.value)} className="w-72" data-testid="students-search" />
      </div>

      <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-slate-50">
            <tr className="text-left text-xs uppercase tracking-[0.1em] text-slate-500">
              <th className="px-4 py-3">Name</th><th className="px-4 py-3">Age</th><th className="px-4 py-3">Skill</th>
              <th className="px-4 py-3">Parent</th><th className="px-4 py-3">Emergency contact</th>
              <th className="px-4 py-3">Waiver</th><th className="px-4 py-3">Status</th>
            </tr>
          </thead>
          <tbody>
            {loading && <tr><td colSpan={7} className="py-10 text-center text-slate-500">Loading…</td></tr>}
            {!loading && filtered.length === 0 && <tr><td colSpan={7} className="py-10 text-center text-slate-500">No students yet.</td></tr>}
            {filtered.map((s) => (
              <tr key={s.id} className="border-b border-slate-100 hover:bg-slate-50">
                <td className="px-4 py-3">
                  <div className="font-medium text-slate-900">{s.first_name} {s.last_name}</div>
                  <div className="text-xs text-slate-500">DOB {formatDate(s.dob)}</div>
                </td>
                <td className="px-4 py-3">{s.age}</td>
                <td className="px-4 py-3 capitalize">{s.skill_level}</td>
                <td className="px-4 py-3">
                  <div className="text-slate-900">{s.parent?.name}</div>
                  <div className="text-xs text-slate-500">{s.parent?.email}</div>
                </td>
                <td className="px-4 py-3 text-slate-700 text-xs">
                  <div>{s.emergency_contact_name}</div>
                  <div className="text-slate-500">{s.emergency_contact_phone}</div>
                </td>
                <td className="px-4 py-3"><StatusBadge status={s.waiver_accepted ? "approved" : "pending"} /></td>
                <td className="px-4 py-3"><StatusBadge status={s.status} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
