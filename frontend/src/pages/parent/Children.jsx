import { useEffect, useState } from "react";
import { api, formatApiError, currency, formatDate } from "../../lib/api";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "../../components/ui/select";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "../../components/ui/dialog";
import { Textarea } from "../../components/ui/textarea";
import { Checkbox } from "../../components/ui/checkbox";
import StatusBadge from "../../components/StatusBadge";
import { toast } from "sonner";
import { Plus, BookOpen } from "lucide-react";

const SKILLS = ["beginner", "intermediate", "advanced"];
const T_SIZES = ["XS", "S", "M", "L", "XL"];

const emptyChild = {
  first_name: "", last_name: "", dob: "", skill_level: "beginner",
  emergency_contact_name: "", emergency_contact_phone: "",
  medical_notes: "", waiver_accepted: false,
  t_shirt_size: "M", previous_experience: "",
};

export default function ParentChildren() {
  const [children, setChildren] = useState([]);
  const [sessions, setSessions] = useState([]);
  const [enrollments, setEnrollments] = useState([]);
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState(emptyChild);
  const [enrollOpen, setEnrollOpen] = useState(null);
  const [enrollSession, setEnrollSession] = useState("");

  const load = async () => {
    const [c, s, e] = await Promise.all([
      api.get("/students"),
      api.get("/sessions"),
      api.get("/enrollments"),
    ]);
    setChildren(c.data); setSessions(s.data); setEnrollments(e.data);
  };
  useEffect(() => { load(); }, []);

  const save = async () => {
    if (!form.waiver_accepted) { toast.error("Please accept the waiver"); return; }
    try {
      await api.post("/students", form);
      toast.success("Child registered"); setOpen(false); setForm(emptyChild); load();
    } catch (e) {
      toast.error(formatApiError(e.response?.data?.detail));
    }
  };

  const enroll = async () => {
    try {
      const { data } = await api.post("/enrollments", { session_id: enrollSession, student_id: enrollOpen });
      toast.success(data.waitlisted ? "Session is full. Child added to waitlist." : data.approval_status === "pending" ? "Enrollment requested. Admin approval is pending." : "Enrolled successfully");
      setEnrollOpen(null); load();
    } catch (e) {
      toast.error(formatApiError(e.response?.data?.detail));
    }
  };

  const childEnrollments = (sid) => enrollments.filter((e) => e.student_id === sid && e.status === "active");
  const seatsLabel = (session) => {
    if (session.is_full) return "Full";
    if (typeof session.available_seats === "number") return `${session.available_seats} spots left`;
    return "Open";
  };

  return (
    <div className="space-y-6" data-testid="parent-children">
      <div className="flex items-end justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-3xl md:text-4xl font-display font-bold tracking-tighter text-slate-900">My Children</h1>
          <p className="text-sm text-slate-600 mt-1">Register children and enroll them in classes</p>
        </div>
        <Button onClick={() => { setForm(emptyChild); setOpen(true); }} data-testid="add-child-button" className="bg-blue-600 hover:bg-blue-500 text-white"><Plus className="w-4 h-4 mr-1.5" /> Add child</Button>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {children.length === 0 && <div className="md:col-span-2 bg-white border border-slate-200 rounded-xl p-10 text-center text-slate-500">No children registered yet. Click "Add child" to begin.</div>}
        {children.map((c) => (
          <div key={c.id} className="bg-white border border-slate-200 rounded-xl p-6">
            <div className="flex justify-between items-start">
              <div>
                <div className="font-display font-bold text-xl tracking-tight text-slate-900">{c.first_name} {c.last_name}</div>
                <div className="text-xs text-slate-500 mt-0.5">Age {c.age} · {c.skill_level}</div>
              </div>
              <StatusBadge status={c.status} />
            </div>
            {c.medical_notes && <div className="mt-3 p-3 rounded-lg bg-amber-50 border border-amber-200 text-xs text-amber-800"><strong>Medical:</strong> {c.medical_notes}</div>}
            <div className="mt-4">
              <div className="text-xs uppercase tracking-[0.1em] text-slate-500 font-semibold mb-2">Enrolled in</div>
              {childEnrollments(c.id).length === 0 && <div className="text-sm text-slate-500">Not enrolled in any session yet.</div>}
              {childEnrollments(c.id).map((e) => (
                <div key={e.id} className="flex justify-between items-center p-2 rounded border border-slate-100 mb-1">
                  <span className="text-sm text-slate-700">{e.session?.name}</span>
                  <div className="flex items-center gap-2">
                    {e.approval_status && e.approval_status !== "approved" && <StatusBadge status={e.approval_status} />}
                    <span className="text-xs text-blue-600 font-semibold">{currency(e.session?.monthly_price)}/mo</span>
                  </div>
                </div>
              ))}
              <Button variant="outline" size="sm" onClick={() => { setEnrollOpen(c.id); setEnrollSession(""); }} data-testid={`enroll-${c.id}`} className="mt-3 text-blue-600 border-blue-200 hover:bg-blue-50">
                <BookOpen className="w-3.5 h-3.5 mr-1.5" /> Enroll in session
              </Button>
            </div>
          </div>
        ))}
      </div>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-w-xl">
          <DialogHeader><DialogTitle className="font-display tracking-tight">Register child</DialogTitle></DialogHeader>
          <div className="grid grid-cols-2 gap-4">
            <div><Label>First name</Label><Input value={form.first_name} onChange={(e) => setForm({ ...form, first_name: e.target.value })} data-testid="child-first-name" className="mt-1" /></div>
            <div><Label>Last name</Label><Input value={form.last_name} onChange={(e) => setForm({ ...form, last_name: e.target.value })} data-testid="child-last-name" className="mt-1" /></div>
            <div><Label>Date of birth</Label><Input type="date" value={form.dob} onChange={(e) => setForm({ ...form, dob: e.target.value })} data-testid="child-dob" className="mt-1" /></div>
            <div>
              <Label>Skill level</Label>
              <Select value={form.skill_level} onValueChange={(v) => setForm({ ...form, skill_level: v })}>
                <SelectTrigger className="mt-1"><SelectValue /></SelectTrigger>
                <SelectContent>{SKILLS.map((s) => <SelectItem key={s} value={s} className="capitalize">{s}</SelectItem>)}</SelectContent>
              </Select>
            </div>
            <div><Label>Emergency contact name</Label><Input value={form.emergency_contact_name} onChange={(e) => setForm({ ...form, emergency_contact_name: e.target.value })} data-testid="child-emergency-name" className="mt-1" /></div>
            <div><Label>Emergency contact phone</Label><Input value={form.emergency_contact_phone} onChange={(e) => setForm({ ...form, emergency_contact_phone: e.target.value })} data-testid="child-emergency-phone" className="mt-1" /></div>
            <div>
              <Label>T-shirt size</Label>
              <Select value={form.t_shirt_size} onValueChange={(v) => setForm({ ...form, t_shirt_size: v })}>
                <SelectTrigger className="mt-1" data-testid="child-tshirt"><SelectValue /></SelectTrigger>
                <SelectContent>{T_SIZES.map((s) => <SelectItem key={s} value={s}>{s}</SelectItem>)}</SelectContent>
              </Select>
            </div>
            <div><Label>Previous experience</Label><Input value={form.previous_experience} onChange={(e) => setForm({ ...form, previous_experience: e.target.value })} placeholder="e.g. 1 year at school" data-testid="child-prev-exp" className="mt-1" /></div>
            <div className="col-span-2"><Label>Medical notes</Label><Textarea value={form.medical_notes} onChange={(e) => setForm({ ...form, medical_notes: e.target.value })} className="mt-1" rows={2} /></div>
            <label className="col-span-2 flex items-start gap-2 p-3 rounded-lg border border-slate-200 cursor-pointer">
              <Checkbox checked={form.waiver_accepted} onCheckedChange={(v) => setForm({ ...form, waiver_accepted: !!v })} data-testid="child-waiver" />
              <div className="text-sm text-slate-700">
                <div className="font-medium">Liability waiver</div>
                <div className="text-xs text-slate-500 mt-1">I confirm my child is fit to play and accept the academy's terms of service.</div>
              </div>
            </label>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setOpen(false)}>Cancel</Button>
            <Button onClick={save} className="bg-blue-600 hover:bg-blue-500 text-white" data-testid="save-child">Register</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={!!enrollOpen} onOpenChange={(v) => !v && setEnrollOpen(null)}>
        <DialogContent>
          <DialogHeader><DialogTitle className="font-display tracking-tight">Enroll in session</DialogTitle></DialogHeader>
          <div>
            <Label>Select session</Label>
            <Select value={enrollSession} onValueChange={setEnrollSession}>
              <SelectTrigger className="mt-1" data-testid="enroll-session-select"><SelectValue placeholder="Pick a session" /></SelectTrigger>
              <SelectContent>
                {sessions.filter((s) => s.status === "active").map((s) => (
                  <SelectItem key={s.id} value={s.id}>
                    {s.name} · {currency(s.monthly_price)}/mo · {s.skill_level} · {s.is_full ? "Join waitlist" : seatsLabel(s)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setEnrollOpen(null)}>Cancel</Button>
            <Button onClick={enroll} disabled={!enrollSession} className="bg-blue-600 hover:bg-blue-500 text-white" data-testid="confirm-enroll">Enroll</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
