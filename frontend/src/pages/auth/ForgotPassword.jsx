import { useState } from "react";
import { Link } from "react-router-dom";
import { useAuth } from "../../contexts/AuthContext";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import { toast } from "sonner";

export default function ForgotPassword() {
  const { resetPassword } = useAuth();
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    try {
      await resetPassword(email);
      toast.success("If that email exists, a reset link has been sent.");
    } catch (err) {
      toast.error(err.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="min-h-screen bg-slate-50 flex items-center justify-center p-6 font-body">
      <div className="w-full max-w-md bg-white border border-slate-200 rounded-xl p-6">
        <h1 className="text-3xl font-display font-bold tracking-tight text-slate-900">Reset password</h1>
        <p className="text-sm text-slate-600 mt-2">Enter your account email and we’ll send a reset link.</p>
        <form onSubmit={submit} className="mt-6 space-y-4">
          <div>
            <Label>Email</Label>
            <Input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required className="mt-1" />
          </div>
          <Button disabled={busy} className="w-full bg-blue-600 hover:bg-blue-500 text-white">
            {busy ? "Sending..." : "Send reset link"}
          </Button>
        </form>
        <Link to="/login" className="block text-center text-sm text-blue-600 hover:underline mt-5">Back to sign in</Link>
      </div>
    </div>
  );
}
