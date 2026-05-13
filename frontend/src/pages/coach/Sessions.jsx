import { useEffect, useState } from "react";
import { api, currency } from "../../lib/api";
import { Link } from "react-router-dom";
import StatusBadge from "../../components/StatusBadge";

export default function CoachSessions() {
  const [items, setItems] = useState([]);
  useEffect(() => { api.get("/sessions").then((r) => setItems(r.data)); }, []);

  return (
    <div className="space-y-6" data-testid="coach-sessions">
      <div>
        <h1 className="text-3xl md:text-4xl font-display font-bold tracking-tighter text-slate-900">My Sessions</h1>
        <p className="text-sm text-slate-600 mt-1">Open a session to mark attendance and add notes</p>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {items.length === 0 && <div className="text-sm text-slate-500 col-span-full">No sessions assigned yet.</div>}
        {items.map((s) => (
          <Link key={s.id} to={`/coach/sessions/${s.id}`} data-testid={`coach-session-card-${s.id}`} className="block bg-white border border-slate-200 rounded-xl p-6 hover:-translate-y-[2px] hover:shadow-md transition-all">
            <div className="flex justify-between items-start">
              <div>
                <div className="font-display font-semibold text-slate-900 tracking-tight">{s.name}</div>
                <div className="text-xs text-slate-500 mt-0.5 capitalize">{s.skill_level} · {s.age_group}</div>
              </div>
              <StatusBadge status={s.status} />
            </div>
            <div className="mt-4 text-xs text-slate-600">{(s.days_of_week || []).join(", ")} · {s.start_time}–{s.end_time}</div>
            <div className="mt-3 flex items-center justify-between">
              <span className="text-xs text-slate-500">{s.location}</span>
              <span className="text-blue-600 font-semibold">{currency(s.monthly_price)}/mo</span>
            </div>
          </Link>
        ))}
      </div>
    </div>
  );
}
