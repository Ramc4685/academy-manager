import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, formatApiError } from "../../lib/api";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import { toast } from "sonner";

export default function ResetPassword() {
  const { token } = useParams();
  const navigate = useNavigate();
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    try {
      await api.post("/auth/reset-password", { token, password });
      toast.success("Password updated. Sign in with your new password.");
      navigate("/login", { replace: true });
    } catch (err) {
      toast.error(formatApiError(err.response?.data?.detail));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="min-h-screen bg-slate-50 flex items-center justify-center p-6 font-body">
      <div className="w-full max-w-md bg-white border border-slate-200 rounded-xl p-6">
        <h1 className="text-3xl font-display font-bold tracking-tight text-slate-900">Choose a new password</h1>
        <form onSubmit={submit} className="mt-6 space-y-4">
          <div>
            <Label>New password</Label>
            <Input type="password" minLength={6} value={password} onChange={(e) => setPassword(e.target.value)} required className="mt-1" />
          </div>
          <Button disabled={busy} className="w-full bg-blue-600 hover:bg-blue-500 text-white">
            {busy ? "Saving..." : "Update password"}
          </Button>
        </form>
        <Link to="/login" className="block text-center text-sm text-blue-600 hover:underline mt-5">Back to sign in</Link>
      </div>
    </div>
  );
}
