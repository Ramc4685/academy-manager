import { useEffect, useState } from "react";
import { api, formatDate } from "../../lib/api";

export default function ParentProgress() {
  const [children, setChildren] = useState([]);
  const [notes, setNotes] = useState([]);

  useEffect(() => {
    api.get("/students").then((r) => setChildren(r.data));
    api.get("/progress-notes").then((r) => setNotes(r.data));
  }, []);

  return (
    <div className="space-y-6" data-testid="parent-progress">
      <div>
        <h1 className="text-3xl md:text-4xl font-display font-bold tracking-tighter text-slate-900">Progress</h1>
        <p className="text-sm text-slate-600 mt-1">Coach notes and feedback for your children</p>
      </div>
      {children.length === 0 && <div className="bg-white border border-slate-200 rounded-xl p-10 text-center text-slate-500">Register a child first to see progress.</div>}
      {children.map((c) => {
        const cNotes = notes.filter((n) => n.student_id === c.id);
        return (
          <div key={c.id} className="bg-white border border-slate-200 rounded-xl p-6">
            <div className="font-display font-bold text-xl tracking-tight text-slate-900">{c.first_name} {c.last_name}</div>
            <div className="text-xs text-slate-500 capitalize mt-0.5">{c.skill_level} · Age {c.age}</div>
            <div className="mt-4 space-y-2">
              {cNotes.length === 0 && <div className="text-sm text-slate-500">No coach notes yet.</div>}
              {cNotes.map((n) => (
                <div key={n.id} className="p-3 rounded-lg bg-slate-50 border border-slate-100">
                  <div className="text-xs text-slate-500">{formatDate(n.created_at)}</div>
                  <div className="text-sm text-slate-800 mt-1">{n.note}</div>
                </div>
              ))}
            </div>
          </div>
        );
      })}
    </div>
  );
}
