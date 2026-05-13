import { useState } from "react";
import { Link, useNavigate, useLocation } from "react-router-dom";
import { useAuth } from "../../contexts/AuthContext";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import { toast } from "sonner";

const HERO = "https://static.prod-images.emergentagent.com/jobs/c735a2b3-2fb1-4fa5-a75c-2007226ca62e/images/1d1cfafe28a9d8df9f22f211189ef097f1bb5d348846857bdee5ba711ec35327.png";

export default function Login() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    try {
      const u = await login(email, password);
      toast.success(`Welcome back, ${u.name || u.email}`);
      const dest = u.role === "admin" ? "/admin/dashboard" : u.role === "coach" ? "/coach/dashboard" : "/parent/dashboard";
      navigate(location.state?.from || dest, { replace: true });
    } catch (err) {
      toast.error(err.message);
    } finally {
      setBusy(false);
    }
  };

  const fillDemo = (role) => {
    if (role === "admin") { setEmail("admin@badminton.app"); setPassword("Admin@12345"); }
    if (role === "coach") { setEmail("coach@badminton.app"); setPassword("Coach@12345"); }
    if (role === "parent") { setEmail("parent@badminton.app"); setPassword("Parent@12345"); }
  };

  return (
    <div className="min-h-screen flex font-body">
      <div className="hidden lg:block w-1/2 relative">
        <img src={HERO} alt="Badminton court" className="absolute inset-0 w-full h-full object-cover" />
        <div className="absolute inset-0 bg-slate-900/55" />
        <div className="relative h-full flex flex-col justify-between p-12 text-white">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-lg bg-yellow-400 flex items-center justify-center text-slate-900 font-display font-bold text-xl">B</div>
            <div>
              <div className="font-display font-bold text-lg tracking-tight">Badminton</div>
              <div className="text-[11px] text-white/70 uppercase tracking-[0.18em]">Academy Manager</div>
            </div>
          </div>
          <div>
            <h1 className="text-4xl lg:text-5xl font-display font-bold tracking-tighter">Run a premium academy. <span className="text-yellow-400">Powered by precision.</span></h1>
            <p className="mt-4 text-white/80 max-w-md leading-relaxed">Sessions, students, payments, payouts, attendance, and profit — all in one professional dashboard.</p>
          </div>
        </div>
      </div>

      <div className="flex-1 flex items-center justify-center p-6 bg-slate-50">
        <div className="w-full max-w-md">
          <div className="lg:hidden flex items-center gap-3 mb-8">
            <div className="w-10 h-10 rounded-lg bg-yellow-400 flex items-center justify-center text-slate-900 font-display font-bold text-xl">B</div>
            <div>
              <div className="font-display font-bold tracking-tight text-slate-900">Badminton</div>
              <div className="text-[11px] text-slate-500 uppercase tracking-[0.18em]">Academy Manager</div>
            </div>
          </div>
          <h2 className="text-3xl md:text-4xl font-display font-bold tracking-tighter text-slate-900">Sign in</h2>
          <p className="mt-2 text-sm text-slate-600">Welcome back. Enter your credentials.</p>

          <form onSubmit={submit} className="mt-8 space-y-5" data-testid="login-form">
            <div>
              <Label htmlFor="email" className="text-slate-700">Email</Label>
              <Input id="email" data-testid="login-email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} required className="mt-1.5" placeholder="you@example.com" />
            </div>
            <div>
              <Label htmlFor="password" className="text-slate-700">Password</Label>
              <Input id="password" data-testid="login-password" type="password" value={password} onChange={(e) => setPassword(e.target.value)} required className="mt-1.5" placeholder="••••••••" />
            </div>
            <Button type="submit" disabled={busy} data-testid="login-submit" className="w-full bg-blue-600 hover:bg-blue-500 text-white font-medium">
              {busy ? "Signing in…" : "Sign in"}
            </Button>
          </form>

          <div className="mt-6 text-sm text-slate-600 text-center">
            New parent? <Link to="/register" className="text-blue-600 hover:underline font-medium" data-testid="link-register">Create an account</Link>
          </div>

          <div className="mt-8 p-4 border border-slate-200 rounded-xl bg-white">
            <div className="text-[11px] uppercase tracking-[0.18em] text-slate-500 font-bold mb-3">Quick demo access</div>
            <div className="flex flex-wrap gap-2">
              <button type="button" onClick={() => fillDemo("admin")} data-testid="demo-admin" className="text-xs px-3 py-1.5 rounded-full border border-slate-200 hover:bg-slate-50 text-slate-700">Admin</button>
              <button type="button" onClick={() => fillDemo("coach")} data-testid="demo-coach" className="text-xs px-3 py-1.5 rounded-full border border-slate-200 hover:bg-slate-50 text-slate-700">Coach</button>
              <button type="button" onClick={() => fillDemo("parent")} data-testid="demo-parent" className="text-xs px-3 py-1.5 rounded-full border border-slate-200 hover:bg-slate-50 text-slate-700">Parent</button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
