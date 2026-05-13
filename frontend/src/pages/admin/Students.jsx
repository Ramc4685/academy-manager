import { useEffect, useState } from "react";
import { api, formatApiError, formatDate, currentPeriod } from "../../lib/api";
import { Input } from "../../components/ui/input";
import { Button } from "../../components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "../../components/ui/select";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "../../components/ui/dialog";
import StatusBadge from "../../components/StatusBadge";
import { toast } from "sonner";
import { Pause, Play, ArrowRightLeft } from "lucide-react";

export default function AdminStudents() {
  const [items, setItems] = useState([]);
  const [sessions, setSessions] = useState([]);
  const [filter, setFilter] = useState("");
  const [enrolFilter, setEnrolFilter] = useState("all"); // all | enrolled | not_enrolled
  const [loading, setLoading] = useState(true);
  const [pauseFor, setPauseFor] = useState(null); // enrollment obj
  const [pausePeriod, setPausePeriod] = useState(currentPeriod());
  const [transferFor, setTransferFor] = useState(null);
  const [transferForm, setTransferForm] = useState({ to_session_id: "", effective_month: currentPeriod(), permanent: true });

  const load = async () => {
    setLoading(true);
    const [s, sess] = await Promise.all([api.get("/students"), api.get("/sessions")]);
    setItems(s.data);
    setSessions(sess.data);
    setLoading(false);
  };
  useEffect(() => { load(); }, []);

  const pause = async () => {
    try {
      await api.post(`/enrollments/${pauseFor.enrollment_id}/pause-month?period=${pausePeriod}`);
      toast.success(`Paused ${pauseFor.session_name} for ${pausePeriod}`);
      setPauseFor(null); load();
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
  };

  const resume = async (enr, period) => {
    await api.post(`/enrollments/${enr.enrollment_id}/resume-month?period=${period}`);
    toast.success(`Resumed ${period}`); load();
  };

  const doTransfer = async () => {
    try {
      await api.post(`/enrollments/${transferFor.enrollment_id}/transfer`, transferForm);
      toast.success(transferForm.permanent ? "Transferred permanently" : `Override set for ${transferForm.effective_month}`);
      setTransferFor(null); load();
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
  };

  const filtered = items.filter((s) => {
    if (filter) {
      const t = `${s.first_name} ${s.last_name} ${s.parent?.email || ""}`.toLowerCase();
      if (!t.includes(filter.toLowerCase())) return false;
    }
    const hasEnroll = (s.enrollments || []).length > 0;
    if (enrolFilter === "enrolled" && !hasEnroll) return false;
    if (enrolFilter === "not_enrolled" && hasEnroll) return false;
    return true;
  });

  const enrolled = items.filter((s) => (s.enrollments || []).length > 0).length;
  const notEnrolled = items.length - enrolled;

  return (
    <div className="space-y-6" data-testid="admin-students">
      <div className="flex items-end justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-3xl md:text-4xl font-display font-bold tracking-tighter text-slate-900">Students</h1>
          <p className="text-sm text-slate-600 mt-1">
            {items.length} registered ·
            <span className="ml-1 text-emerald-700 font-semibold">{enrolled} enrolled</span> ·
            <span className="ml-1 text-amber-700 font-semibold">{notEnrolled} not enrolled</span>
          </p>
        </div>
        <div className="flex gap-2">
          <Select value={enrolFilter} onValueChange={setEnrolFilter}>
            <SelectTrigger className="w-44" data-testid="enrol-filter"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All students</SelectItem>
              <SelectItem value="enrolled">Enrolled</SelectItem>
              <SelectItem value="not_enrolled">Not enrolled</SelectItem>
            </SelectContent>
          </Select>
          <Input placeholder="Search…" value={filter} onChange={(e) => setFilter(e.target.value)} className="w-64" data-testid="students-search" />
        </div>
      </div>

      <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-slate-50">
            <tr className="text-left text-xs uppercase tracking-[0.1em] text-slate-500">
              <th className="px-4 py-3">Name</th><th className="px-4 py-3">Age</th><th className="px-4 py-3">Skill</th>
              <th className="px-4 py-3">Parent</th>
              <th className="px-4 py-3">Enrolled In</th>
              <th className="px-4 py-3">Waiver</th>
              <th className="px-4 py-3"></th>
            </tr>
          </thead>
          <tbody>
            {loading && <tr><td colSpan={7} className="py-10 text-center text-slate-500">Loading…</td></tr>}
            {!loading && filtered.length === 0 && <tr><td colSpan={7} className="py-10 text-center text-slate-500">No students match.</td></tr>}
            {filtered.map((s) => (
              <tr key={s.id} className="border-b border-slate-100 hover:bg-slate-50 align-top">
                <td className="px-4 py-3">
                  <div className="font-medium text-slate-900">{s.first_name} {s.last_name}</div>
                  <div className="text-xs text-slate-500">DOB {formatDate(s.dob) || "—"}</div>
                </td>
                <td className="px-4 py-3">{s.age || "—"}</td>
                <td className="px-4 py-3 capitalize">{s.skill_level}</td>
                <td className="px-4 py-3">
                  <div className="text-slate-900 text-xs">{s.parent?.name}</div>
                  <div className="text-xs text-slate-500">{s.parent?.email}</div>
                </td>
                <td className="px-4 py-3">
                  {(s.enrollments || []).length === 0 && (
                    <span className="text-xs px-2 py-0.5 rounded-full bg-amber-50 text-amber-700 border border-amber-200">Not enrolled</span>
                  )}
                  {(s.enrollments || []).map((e) => (
                    <div key={e.enrollment_id} className="mb-1.5 last:mb-0">
                      <div className="text-xs text-slate-700">{e.session_name}</div>
                      <div className="flex gap-1 mt-0.5 flex-wrap items-center">
                        <StatusBadge status={e.billing_type === "Standard" ? "active" : (e.billing_type === "NoCharge" ? "excused" : "pending")} />
                        {(e.skip_periods || []).length > 0 && (
                          <span className="text-[10px] px-1.5 py-0.5 rounded bg-slate-100 text-slate-600">
                            Paused: {(e.skip_periods || []).join(", ")}
                          </span>
                        )}
                        <button data-testid={`pause-${e.enrollment_id}`} onClick={() => { setPauseFor(e); setPausePeriod(currentPeriod()); }} className="text-[10px] px-1.5 py-0.5 rounded bg-blue-50 text-blue-700 hover:bg-blue-100 flex items-center gap-0.5">
                          <Pause className="w-2.5 h-2.5" /> Pause
                        </button>
                        <button data-testid={`transfer-${e.enrollment_id}`} onClick={() => { setTransferFor(e); setTransferForm({ to_session_id: "", effective_month: currentPeriod(), permanent: true }); }} className="text-[10px] px-1.5 py-0.5 rounded bg-yellow-50 text-yellow-800 hover:bg-yellow-100 flex items-center gap-0.5">
                          <ArrowRightLeft className="w-2.5 h-2.5" /> Move
                        </button>
                        {(e.skip_periods || []).map((p) => (
                          <button key={p} onClick={() => resume(e, p)} title={`Resume ${p}`} className="text-[10px] px-1.5 py-0.5 rounded bg-emerald-50 text-emerald-700 hover:bg-emerald-100 flex items-center gap-0.5">
                            <Play className="w-2.5 h-2.5" /> Resume {p}
                          </button>
                        ))}
                      </div>
                    </div>
                  ))}
                </td>
                <td className="px-4 py-3"><StatusBadge status={s.waiver_accepted ? "approved" : "pending"} /></td>
                <td className="px-4 py-3"></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <Dialog open={!!pauseFor} onOpenChange={(v) => !v && setPauseFor(null)}>
        <DialogContent>
          <DialogHeader><DialogTitle className="font-display tracking-tight">Pause this kid for a month</DialogTitle></DialogHeader>
          <div className="space-y-3">
            <div className="text-sm text-slate-600">Kid will be skipped from <span className="font-medium">{pauseFor?.session_name}</span> for one month. No payment will be generated for that period. You can resume later.</div>
            <div>
              <label className="text-sm text-slate-700">Month to skip</label>
              <Input type="month" value={pausePeriod} onChange={(e) => setPausePeriod(e.target.value)} className="mt-1" data-testid="pause-period-input" />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setPauseFor(null)}>Cancel</Button>
            <Button onClick={pause} className="bg-blue-600 hover:bg-blue-500 text-white" data-testid="confirm-pause">Pause month</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={!!transferFor} onOpenChange={(v) => !v && setTransferFor(null)}>
        <DialogContent>
          <DialogHeader><DialogTitle className="font-display tracking-tight">Transfer / Move to another session</DialogTitle></DialogHeader>
          <div className="space-y-3">
            <div className="text-sm text-slate-600">Current session: <span className="font-medium">{transferFor?.session_name}</span></div>
            <div>
              <label className="text-sm text-slate-700">Move to</label>
              <Select value={transferForm.to_session_id} onValueChange={(v) => setTransferForm({ ...transferForm, to_session_id: v })}>
                <SelectTrigger className="mt-1" data-testid="transfer-to"><SelectValue placeholder="Pick a session" /></SelectTrigger>
                <SelectContent>
                  {sessions.filter((s) => s.id !== transferFor?.session_id && s.status === "active").map((s) => (
                    <SelectItem key={s.id} value={s.id}>{s.name}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div>
              <label className="text-sm text-slate-700">Effective month</label>
              <Input type="month" value={transferForm.effective_month} onChange={(e) => setTransferForm({ ...transferForm, effective_month: e.target.value })} className="mt-1" />
            </div>
            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" checked={transferForm.permanent} onChange={(e) => setTransferForm({ ...transferForm, permanent: e.target.checked })} data-testid="transfer-permanent" />
              <span>Permanent move (uncheck = just for this month)</span>
            </label>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setTransferFor(null)}>Cancel</Button>
            <Button onClick={doTransfer} disabled={!transferForm.to_session_id} className="bg-blue-600 hover:bg-blue-500 text-white" data-testid="confirm-transfer">Move</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
