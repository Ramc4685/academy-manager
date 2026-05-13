import { useEffect, useState } from "react";
import { api, formatApiError, currency, formatDate } from "../../lib/api";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "../../components/ui/select";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "../../components/ui/dialog";
import { Checkbox } from "../../components/ui/checkbox";
import StatusBadge from "../../components/StatusBadge";
import { toast } from "sonner";
import { Plus, Pencil, Trash2 } from "lucide-react";

const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const SKILL = ["beginner", "intermediate", "advanced"];

const empty = {
  name: "", skill_level: "beginner", age_group: "", start_date: "", end_date: "",
  days_of_week: [], start_time: "17:00", end_time: "18:30", location: "Court A",
  max_students: 12, monthly_price: 120, coach_id: "", status: "active",
};

export default function AdminSessions() {
  const [sessions, setSessions] = useState([]);
  const [coaches, setCoaches] = useState([]);
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState(null);
  const [form, setForm] = useState(empty);
  const [filter, setFilter] = useState("");
  const [loading, setLoading] = useState(true);

  const load = async () => {
    setLoading(true);
    const [s, c] = await Promise.all([
      api.get("/sessions"),
      api.get("/users?role=coach"),
    ]);
    setSessions(s.data);
    setCoaches(c.data);
    setLoading(false);
  };
  useEffect(() => { load(); }, []);

  const openNew = () => { setEditing(null); setForm(empty); setOpen(true); };
  const openEdit = (s) => {
    setEditing(s.id);
    setForm({
      name: s.name, skill_level: s.skill_level, age_group: s.age_group,
      start_date: s.start_date, end_date: s.end_date, days_of_week: s.days_of_week || [],
      start_time: s.start_time, end_time: s.end_time, location: s.location,
      max_students: s.max_students, monthly_price: s.monthly_price,
      coach_id: s.coach_id || "", status: s.status,
    });
    setOpen(true);
  };

  const toggleDay = (d) => {
    setForm((f) => ({ ...f, days_of_week: f.days_of_week.includes(d) ? f.days_of_week.filter((x) => x !== d) : [...f.days_of_week, d] }));
  };

  const save = async () => {
    try {
      const payload = { ...form, coach_id: form.coach_id || null, max_students: Number(form.max_students), monthly_price: Number(form.monthly_price) };
      if (editing) await api.patch(`/sessions/${editing}`, payload);
      else await api.post("/sessions", payload);
      toast.success(`Session ${editing ? "updated" : "created"}`);
      setOpen(false); load();
    } catch (e) {
      toast.error(formatApiError(e.response?.data?.detail));
    }
  };

  const del = async (id) => {
    if (!confirm("Delete this session?")) return;
    await api.delete(`/sessions/${id}`);
    toast.success("Session deleted");
    load();
  };

  const filtered = sessions.filter((s) => !filter || s.name.toLowerCase().includes(filter.toLowerCase()));

  return (
    <div className="space-y-6" data-testid="admin-sessions">
      <div className="flex items-end justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-3xl md:text-4xl font-display font-bold tracking-tighter text-slate-900">Sessions</h1>
          <p className="text-sm text-slate-600 mt-1">Create and manage classes</p>
        </div>
        <div className="flex gap-2">
          <Input placeholder="Search…" value={filter} onChange={(e) => setFilter(e.target.value)} className="w-56" data-testid="sessions-search" />
          <Button onClick={openNew} data-testid="create-session-button" className="bg-blue-600 hover:bg-blue-500 text-white"><Plus className="w-4 h-4 mr-1.5" /> New Session</Button>
        </div>
      </div>

      <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-slate-50">
            <tr className="text-left text-xs uppercase tracking-[0.1em] text-slate-500">
              <th className="px-4 py-3">Name</th><th className="px-4 py-3">Level</th><th className="px-4 py-3">Schedule</th>
              <th className="px-4 py-3">Coach</th><th className="px-4 py-3">Price</th>
              <th className="px-4 py-3">Status</th><th className="px-4 py-3"></th>
            </tr>
          </thead>
          <tbody>
            {loading && <tr><td colSpan={7} className="py-10 text-center text-slate-500">Loading…</td></tr>}
            {!loading && filtered.length === 0 && <tr><td colSpan={7} className="py-10 text-center text-slate-500">No sessions yet.</td></tr>}
            {filtered.map((s) => (
              <tr key={s.id} className="border-b border-slate-100 hover:bg-slate-50">
                <td className="px-4 py-3">
                  <div className="font-medium text-slate-900">{s.name}</div>
                  <div className="text-xs text-slate-500">{s.age_group} · {s.location}</div>
                </td>
                <td className="px-4 py-3 capitalize">{s.skill_level}</td>
                <td className="px-4 py-3 text-slate-700 text-xs">{(s.days_of_week || []).join(", ")} · {s.start_time}–{s.end_time}</td>
                <td className="px-4 py-3 text-slate-700">{s.coach_name}</td>
                <td className="px-4 py-3 font-semibold text-blue-600">{currency(s.monthly_price)}</td>
                <td className="px-4 py-3"><StatusBadge status={s.status} /></td>
                <td className="px-4 py-3 text-right">
                  <button onClick={() => openEdit(s)} data-testid={`edit-session-${s.id}`} className="p-1.5 hover:bg-slate-100 rounded text-slate-600"><Pencil className="w-4 h-4" /></button>
                  <button onClick={() => del(s.id)} data-testid={`delete-session-${s.id}`} className="p-1.5 hover:bg-slate-100 rounded text-red-600 ml-1"><Trash2 className="w-4 h-4" /></button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-w-2xl max-h-[90vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle className="font-display tracking-tight">{editing ? "Edit Session" : "Create Session"}</DialogTitle>
          </DialogHeader>
          <div className="grid grid-cols-2 gap-4">
            <div className="col-span-2"><Label>Name</Label><Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} data-testid="session-name-input" className="mt-1" /></div>
            <div>
              <Label>Skill level</Label>
              <Select value={form.skill_level} onValueChange={(v) => setForm({ ...form, skill_level: v })}>
                <SelectTrigger className="mt-1" data-testid="session-skill-trigger"><SelectValue /></SelectTrigger>
                <SelectContent>{SKILL.map((s) => <SelectItem key={s} value={s} className="capitalize">{s}</SelectItem>)}</SelectContent>
              </Select>
            </div>
            <div><Label>Age group</Label><Input value={form.age_group} onChange={(e) => setForm({ ...form, age_group: e.target.value })} placeholder="e.g. 8-12" className="mt-1" /></div>
            <div><Label>Start date</Label><Input type="date" value={form.start_date} onChange={(e) => setForm({ ...form, start_date: e.target.value })} className="mt-1" /></div>
            <div><Label>End date</Label><Input type="date" value={form.end_date} onChange={(e) => setForm({ ...form, end_date: e.target.value })} className="mt-1" /></div>
            <div><Label>Start time</Label><Input type="time" value={form.start_time} onChange={(e) => setForm({ ...form, start_time: e.target.value })} className="mt-1" /></div>
            <div><Label>End time</Label><Input type="time" value={form.end_time} onChange={(e) => setForm({ ...form, end_time: e.target.value })} className="mt-1" /></div>
            <div className="col-span-2">
              <Label>Days of week</Label>
              <div className="flex flex-wrap gap-2 mt-2">
                {DAYS.map((d) => (
                  <button type="button" key={d} onClick={() => toggleDay(d)} data-testid={`day-${d}`} className={`px-3 py-1.5 rounded-full text-sm border ${form.days_of_week.includes(d) ? "bg-blue-600 border-blue-600 text-white" : "bg-white border-slate-200 text-slate-700"}`}>{d}</button>
                ))}
              </div>
            </div>
            <div><Label>Location</Label><Input value={form.location} onChange={(e) => setForm({ ...form, location: e.target.value })} className="mt-1" /></div>
            <div><Label>Max students</Label><Input type="number" value={form.max_students} onChange={(e) => setForm({ ...form, max_students: e.target.value })} className="mt-1" /></div>
            <div><Label>Monthly price ($)</Label><Input type="number" value={form.monthly_price} onChange={(e) => setForm({ ...form, monthly_price: e.target.value })} className="mt-1" /></div>
            <div>
              <Label>Coach</Label>
              <Select value={form.coach_id || "none"} onValueChange={(v) => setForm({ ...form, coach_id: v === "none" ? "" : v })}>
                <SelectTrigger className="mt-1" data-testid="session-coach-trigger"><SelectValue placeholder="Unassigned" /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="none">Unassigned</SelectItem>
                  {coaches.map((c) => <SelectItem key={c.id} value={c.id}>{c.name || c.email}</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
            <div>
              <Label>Status</Label>
              <Select value={form.status} onValueChange={(v) => setForm({ ...form, status: v })}>
                <SelectTrigger className="mt-1"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="active">Active</SelectItem>
                  <SelectItem value="cancelled">Cancelled</SelectItem>
                  <SelectItem value="completed">Completed</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setOpen(false)}>Cancel</Button>
            <Button onClick={save} className="bg-blue-600 hover:bg-blue-500 text-white" data-testid="save-session-button">Save</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
