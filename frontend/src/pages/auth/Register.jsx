import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "../../contexts/AuthContext";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import { toast } from "sonner";

export default function Register() {
  const { register } = useAuth();
  const navigate = useNavigate();
  const [form, setForm] = useState({ name: "", email: "", phone: "", password: "" });
  const [busy, setBusy] = useState(false);

  const onChange = (k) => (e) => setForm({ ...form, [k]: e.target.value });

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    try {
      const u = await register(form);
      toast.success(`Account created. Welcome, ${u.name}!`);
      navigate("/parent/dashboard", { replace: true });
    } catch (err) {
      toast.error(err.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center p-6 bg-slate-50 font-body">
      <div className="w-full max-w-md">
        <div className="flex items-center gap-3 mb-8">
          <div className="w-10 h-10 rounded-lg bg-yellow-400 flex items-center justify-center text-slate-900 font-display font-bold text-xl">B</div>
          <div>
            <div className="font-display font-bold tracking-tight text-slate-900">Badminton</div>
            <div className="text-[11px] text-slate-500 uppercase tracking-[0.18em]">Academy Manager</div>
          </div>
        </div>
        <h2 className="text-3xl md:text-4xl font-display font-bold tracking-tighter text-slate-900">Create parent account</h2>
        <p className="mt-2 text-sm text-slate-600">Register to enroll your children in classes.</p>

        <form onSubmit={submit} className="mt-8 space-y-4" data-testid="register-form">
          <div>
            <Label className="text-slate-700">Full name</Label>
            <Input data-testid="register-name" required value={form.name} onChange={onChange("name")} className="mt-1.5" />
          </div>
          <div>
            <Label className="text-slate-700">Email</Label>
            <Input data-testid="register-email" type="email" required value={form.email} onChange={onChange("email")} className="mt-1.5" />
          </div>
          <div>
            <Label className="text-slate-700">Phone (optional)</Label>
            <Input data-testid="register-phone" value={form.phone} onChange={onChange("phone")} className="mt-1.5" />
          </div>
          <div>
            <Label className="text-slate-700">Password</Label>
            <Input data-testid="register-password" type="password" required minLength={6} value={form.password} onChange={onChange("password")} className="mt-1.5" />
          </div>
          <Button type="submit" disabled={busy} data-testid="register-submit" className="w-full bg-blue-600 hover:bg-blue-500 text-white">
            {busy ? "Creating account…" : "Create account"}
          </Button>
        </form>

        <div className="mt-6 text-sm text-slate-600 text-center">
          Already have an account? <Link to="/login" className="text-blue-600 hover:underline font-medium">Sign in</Link>
        </div>
      </div>
    </div>
  );
}
