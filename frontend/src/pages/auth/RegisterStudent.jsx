import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, formatApiError, currency } from "../../lib/api";
import { useAuth } from "../../contexts/AuthContext";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import { Textarea } from "../../components/ui/textarea";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "../../components/ui/select";
import { Checkbox } from "../../components/ui/checkbox";
import { toast } from "sonner";

const SKILLS = ["beginner", "intermediate", "advanced"];
const T_SIZES = ["XS", "S", "M", "L", "XL"];

const empty = {
  parent_name: "", parent_email: "", parent_phone: "", password: "",
  child_first_name: "", child_last_name: "", child_dob: "",
  child_skill_level: "beginner", emergency_contact_name: "", emergency_contact_phone: "",
  medical_notes: "", t_shirt_size: "M", previous_experience: "",
  waiver_accepted: false, session_id: "",
};

export default function RegisterStudent() {
  const navigate = useNavigate();
  const { registerFull } = useAuth();
  const [sessions, setSessions] = useState([]);
  const [form, setForm] = useState(empty);
  const [step, setStep] = useState(1);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.get("/auth/public-sessions").then((r) => setSessions(r.data)).catch(() => setSessions([]));
  }, []);

  const update = (k) => (e) => setForm({ ...form, [k]: e.target.value });
  const seatsLabel = (session) => {
    if (session.is_full) return "Full";
    if (typeof session.available_seats === "number") return `${session.available_seats} spots left`;
    return "Open";
  };

  const validateStep1 = () => {
    if (!form.parent_name || !form.parent_email || !form.parent_phone || !form.password) {
      toast.error("Please fill in all parent fields"); return false;
    }
    if (form.password.length < 6) { toast.error("Password must be at least 6 characters"); return false; }
    return true;
  };
  const validateStep2 = () => {
    if (!form.child_first_name || !form.child_last_name || !form.child_dob || !form.emergency_contact_name || !form.emergency_contact_phone) {
      toast.error("Please fill in all required child fields"); return false;
    }
    if (!form.waiver_accepted) { toast.error("Please accept the waiver to continue"); return false; }
    return true;
  };

  const submit = async () => {
    if (!validateStep2()) return;
    setBusy(true);
    try {
      const data = await registerFull({ ...form, session_id: form.session_id || null });
      toast.success(data.waitlisted ? "Registration complete. Your child is on the waitlist." : data.enrollment_id ? "Registration complete. Enrollment is pending approval." : `Welcome ${data.name}! Your account is active.`);
      if (data.payment_id) {
        try {
          const checkout = await api.post("/billing/checkout-session", {
            payment_id: data.payment_id,
            origin_url: window.location.origin,
          });
          window.location.href = checkout.data.url;
          return;
        } catch (checkoutError) {
          toast.error(formatApiError(checkoutError.response?.data?.detail));
          navigate("/parent/payments", { replace: true });
          return;
        }
      }
      navigate("/parent/dashboard", { replace: true });
    } catch (e) {
      toast.error(formatApiError(e.response?.data?.detail));
    } finally { setBusy(false); }
  };

  return (
    <div className="min-h-screen bg-slate-50 font-body">
      <div className="max-w-3xl mx-auto p-6 lg:p-10">
        <Link to="/login" className="flex items-center gap-3 mb-10">
          <div className="w-10 h-10 rounded-lg bg-yellow-400 flex items-center justify-center text-slate-900 font-display font-bold text-xl">B</div>
          <div>
            <div className="font-display font-bold tracking-tight text-slate-900">BLno Badminton Academy</div>
            <div className="text-[11px] text-slate-500 uppercase tracking-[0.18em]">Student Registration</div>
          </div>
        </Link>

        <h1 className="text-3xl md:text-5xl font-display font-bold tracking-tighter text-slate-900">Register your child</h1>
        <p className="text-slate-600 mt-2">Takes 3 minutes. After submitting, you'll be logged in and can manage everything from your parent portal.</p>

        <div className="flex items-center gap-2 mt-8">
          <div className={`flex-1 h-1.5 rounded-full ${step >= 1 ? "bg-blue-600" : "bg-slate-200"}`} />
          <div className={`flex-1 h-1.5 rounded-full ${step >= 2 ? "bg-blue-600" : "bg-slate-200"}`} />
          <div className={`flex-1 h-1.5 rounded-full ${step >= 3 ? "bg-blue-600" : "bg-slate-200"}`} />
        </div>
        <div className="text-xs text-slate-500 mt-2">Step {step} of 3 — {step === 1 ? "Parent account" : step === 2 ? "Child details" : "Pick a session (optional)"}</div>

        {step === 1 && (
          <div className="mt-8 bg-white border border-slate-200 rounded-xl p-6 grid grid-cols-2 gap-4" data-testid="reg-step-1">
            <div className="col-span-2"><Label>Your full name</Label><Input value={form.parent_name} onChange={update("parent_name")} className="mt-1" data-testid="reg-parent-name" /></div>
            <div><Label>Email</Label><Input type="email" value={form.parent_email} onChange={update("parent_email")} className="mt-1" data-testid="reg-parent-email" /></div>
            <div><Label>Phone (mobile)</Label><Input value={form.parent_phone} onChange={update("parent_phone")} placeholder="10-digit US phone" className="mt-1" data-testid="reg-parent-phone" /></div>
            <div className="col-span-2"><Label>Create a password</Label><Input type="password" minLength={6} value={form.password} onChange={update("password")} className="mt-1" data-testid="reg-password" /></div>
            <div className="col-span-2 flex justify-end">
              <Button onClick={() => validateStep1() && setStep(2)} data-testid="reg-next-1" className="bg-blue-600 hover:bg-blue-500 text-white">Continue →</Button>
            </div>
          </div>
        )}

        {step === 2 && (
          <div className="mt-8 bg-white border border-slate-200 rounded-xl p-6 grid grid-cols-2 gap-4" data-testid="reg-step-2">
            <div><Label>Child's first name</Label><Input value={form.child_first_name} onChange={update("child_first_name")} className="mt-1" data-testid="reg-child-first" /></div>
            <div><Label>Last name</Label><Input value={form.child_last_name} onChange={update("child_last_name")} className="mt-1" data-testid="reg-child-last" /></div>
            <div><Label>Date of birth</Label><Input type="date" value={form.child_dob} onChange={update("child_dob")} className="mt-1" data-testid="reg-child-dob" /></div>
            <div>
              <Label>Skill level</Label>
              <Select value={form.child_skill_level} onValueChange={(v) => setForm({ ...form, child_skill_level: v })}>
                <SelectTrigger className="mt-1" data-testid="reg-skill"><SelectValue /></SelectTrigger>
                <SelectContent>{SKILLS.map((s) => <SelectItem key={s} value={s} className="capitalize">{s}</SelectItem>)}</SelectContent>
              </Select>
            </div>
            <div><Label>Emergency contact name</Label><Input value={form.emergency_contact_name} onChange={update("emergency_contact_name")} className="mt-1" data-testid="reg-emergency-name" /></div>
            <div><Label>Emergency contact phone</Label><Input value={form.emergency_contact_phone} onChange={update("emergency_contact_phone")} className="mt-1" data-testid="reg-emergency-phone" /></div>
            <div>
              <Label>T-shirt size</Label>
              <Select value={form.t_shirt_size} onValueChange={(v) => setForm({ ...form, t_shirt_size: v })}>
                <SelectTrigger className="mt-1" data-testid="reg-tshirt"><SelectValue /></SelectTrigger>
                <SelectContent>{T_SIZES.map((s) => <SelectItem key={s} value={s}>{s}</SelectItem>)}</SelectContent>
              </Select>
            </div>
            <div><Label>Previous experience</Label><Input value={form.previous_experience} onChange={update("previous_experience")} placeholder="optional" className="mt-1" /></div>
            <div className="col-span-2"><Label>Medical conditions or allergies</Label><Textarea rows={2} value={form.medical_notes} onChange={update("medical_notes")} placeholder="None / any" className="mt-1" data-testid="reg-medical" /></div>
            <label className="col-span-2 flex items-start gap-2 p-3 rounded-lg border border-slate-200 cursor-pointer">
              <Checkbox checked={form.waiver_accepted} onCheckedChange={(v) => setForm({ ...form, waiver_accepted: !!v })} data-testid="reg-waiver" />
              <div className="text-sm text-slate-700">
                <div className="font-medium">Liability waiver</div>
                <div className="text-xs text-slate-500 mt-1">I confirm my child is fit to play badminton and accept BLno Academy's terms.</div>
              </div>
            </label>
            <div className="col-span-2 flex justify-between">
              <Button variant="outline" onClick={() => setStep(1)}>← Back</Button>
              <Button onClick={() => validateStep2() && setStep(3)} data-testid="reg-next-2" className="bg-blue-600 hover:bg-blue-500 text-white">Continue →</Button>
            </div>
          </div>
        )}

        {step === 3 && (
          <div className="mt-8 bg-white border border-slate-200 rounded-xl p-6 space-y-4" data-testid="reg-step-3">
            <div>
              <div className="font-display font-semibold tracking-tight text-slate-900">Pick a session (optional)</div>
              <p className="text-sm text-slate-600 mt-1">You can skip this and your admin will enroll your child manually, or you can pick one now (subject to approval).</p>
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              <button onClick={() => setForm({ ...form, session_id: "" })} className={`text-left p-4 rounded-xl border-2 transition-all ${!form.session_id ? "border-blue-600 bg-blue-50" : "border-slate-200 hover:border-slate-300"}`} data-testid="reg-no-session">
                <div className="font-medium text-slate-900">Skip for now</div>
                <div className="text-xs text-slate-500 mt-1">Admin will enroll later</div>
              </button>
              {sessions.map((s) => (
                <button
                  key={s.id}
                  type="button"
                  onClick={() => setForm({ ...form, session_id: s.id })}
                  className={`text-left p-4 rounded-xl border-2 transition-all ${form.session_id === s.id ? "border-blue-600 bg-blue-50" : "border-slate-200 hover:border-slate-300"}`}
                  data-testid={`reg-session-${s.id}`}
                >
                  <div className="font-medium text-slate-900 text-sm">{s.name}</div>
                  <div className="text-xs text-slate-500 mt-1 capitalize">{s.skill_level} · {s.start_time}–{s.end_time}</div>
                  <div className="flex items-center justify-between gap-2 mt-1.5">
                    <span className="text-blue-600 font-semibold text-sm">{currency(s.monthly_price)}/mo</span>
                    <span className={`text-xs font-semibold ${s.is_full ? "text-amber-600" : "text-emerald-600"}`}>{s.is_full ? "Join waitlist" : seatsLabel(s)}</span>
                  </div>
                </button>
              ))}
            </div>
            <div className="flex justify-between pt-2">
              <Button variant="outline" onClick={() => setStep(2)}>← Back</Button>
              <Button onClick={submit} disabled={busy} data-testid="reg-submit" className="bg-blue-600 hover:bg-blue-500 text-white">
                {busy ? "Creating…" : "Complete registration"}
              </Button>
            </div>
          </div>
        )}

        <div className="mt-10 text-sm text-slate-600 text-center">
          Already have an account? <Link to="/login" className="text-blue-600 hover:underline font-medium">Sign in</Link>
        </div>
      </div>
    </div>
  );
}
