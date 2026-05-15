import { useEffect, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import {
  createUserWithEmailAndPassword,
  deleteUser,
  sendEmailVerification,
  signInWithEmailAndPassword,
  signInWithPopup,
  GoogleAuthProvider,
  updateProfile,
} from "firebase/auth";
import { api, formatApiError } from "../../lib/api";
import { useAuth } from "../../contexts/AuthContext";
import { auth, isFirebaseConfigured } from "../../lib/firebase";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import { toast } from "sonner";

export default function AcceptInvite() {
  const { token } = useParams();
  const navigate = useNavigate();
  const { refresh } = useAuth();
  const [info, setInfo] = useState(null);
  const [err, setErr] = useState("");
  const [form, setForm] = useState({ name: "", phone: "", password: "" });
  const [busy, setBusy] = useState(false);
  const [needsVerification, setNeedsVerification] = useState(false);

  const firebaseMode = Boolean(auth && isFirebaseConfigured);

  useEffect(() => {
    api.get(`/invites/info/${token}`)
      .then((r) => { setInfo(r.data); setForm((f) => ({ ...f, name: r.data.name || "" })); })
      .catch((e) => setErr(formatApiError(e.response?.data?.detail) || "Invalid invite"));
  }, [token]);

  const finishOnBackend = async (extraPayload = {}) => {
    const { data } = await api.post(`/invites/accept/${token}`, { ...form, ...extraPayload });
    toast.success(`Welcome, ${data.name}!`);
    await refresh();
    const dest = data.role === "coach" ? "/coach/dashboard" : "/parent/dashboard";
    navigate(dest, { replace: true });
  };

  const submit = async (e) => {
    e.preventDefault();
    if (!info) return;
    setBusy(true);
    setNeedsVerification(false);
    let createdFirebaseUser = null;
    try {
      if (firebaseMode) {
        // Sign in first (in case the user already created a Firebase account),
        // otherwise create one.
        try {
          await signInWithEmailAndPassword(auth, info.email, form.password);
        } catch (signInErr) {
          const credential = await createUserWithEmailAndPassword(auth, info.email, form.password);
          createdFirebaseUser = credential.user;
          if (form.name) {
            try { await updateProfile(credential.user, { displayName: form.name }); } catch { /* ignore */ }
          }
        }
        if (!auth.currentUser?.emailVerified) {
          try { await sendEmailVerification(auth.currentUser); } catch { /* ignore */ }
          setNeedsVerification(true);
          toast.message("Verify your email", {
            description: "We sent a verification link to " + info.email + ". Click it, then return here to finish.",
          });
          return;
        }
        await finishOnBackend({ password: undefined });
      } else {
        await finishOnBackend();
      }
    } catch (e2) {
      if (firebaseMode && createdFirebaseUser) {
        try { await deleteUser(createdFirebaseUser); } catch { /* ignore */ }
      }
      const msg = formatApiError(e2.response?.data?.detail) || e2.message;
      toast.error(msg);
    } finally {
      setBusy(false);
    }
  };

  const continueWithGoogle = async () => {
    if (!info) return;
    setBusy(true);
    try {
      const provider = new GoogleAuthProvider();
      provider.addScope("email");
      const cred = await signInWithPopup(auth, provider);
      if (cred.user.email?.toLowerCase() !== info.email.toLowerCase()) {
        toast.error(`Please sign in with ${info.email}.`);
        return;
      }
      await finishOnBackend({ password: undefined });
    } catch (e2) {
      const msg = formatApiError(e2.response?.data?.detail) || e2.message;
      toast.error(msg);
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
            <div className="font-display font-bold tracking-tight text-slate-900">Badminton Academy</div>
            <div className="text-[11px] text-slate-500 uppercase tracking-[0.18em]">Accept Invitation</div>
          </div>
        </div>

        {err && <div className="p-4 rounded-xl bg-red-50 border border-red-200 text-red-700 text-sm">{err}</div>}
        {!err && !info && <div className="text-slate-500 text-sm">Loading invite…</div>}
        {info && (
          <>
            <h2 className="text-3xl font-display font-bold tracking-tighter text-slate-900">Welcome, you've been invited</h2>
            <p className="mt-2 text-sm text-slate-600">Email: <span className="font-medium">{info.email}</span> · Role: <span className="font-medium capitalize">{info.role}</span></p>

            {needsVerification && (
              <div className="mt-6 p-4 rounded-xl bg-amber-50 border border-amber-200 text-amber-800 text-sm">
                Check <span className="font-medium">{info.email}</span> for a verification link. Once verified, return and click <span className="font-medium">Activate account</span> again.
              </div>
            )}

            <form onSubmit={submit} className="mt-8 space-y-4" data-testid="accept-invite-form">
              <div>
                <Label className="text-slate-700">Full name</Label>
                <Input required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} className="mt-1.5" />
              </div>
              <div>
                <Label className="text-slate-700">Phone</Label>
                <Input value={form.phone} onChange={(e) => setForm({ ...form, phone: e.target.value })} className="mt-1.5" />
              </div>
              <div>
                <Label className="text-slate-700">Set password</Label>
                <Input type="password" required minLength={6} value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} className="mt-1.5" />
              </div>
              <Button type="submit" disabled={busy} data-testid="accept-invite-submit" className="w-full bg-blue-600 hover:bg-blue-500 text-white">
                {busy ? "Activating…" : "Activate account"}
              </Button>
            </form>

            {firebaseMode && (
              <div className="mt-5">
                <div className="flex items-center gap-3 text-xs uppercase tracking-[0.18em] text-slate-400">
                  <div className="h-px flex-1 bg-slate-200" />
                  <span>or</span>
                  <div className="h-px flex-1 bg-slate-200" />
                </div>
                <Button
                  type="button"
                  variant="outline"
                  disabled={busy}
                  onClick={continueWithGoogle}
                  className="mt-5 w-full border-slate-200 bg-white text-slate-800 hover:bg-slate-50 font-medium"
                >
                  Continue with Google
                </Button>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
