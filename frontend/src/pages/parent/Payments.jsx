import { useEffect, useState, useCallback, useRef } from "react";
import { useSearchParams } from "react-router-dom";
import { api, formatApiError, currency, formatDate, currentPeriod } from "../../lib/api";
import StatusBadge from "../../components/StatusBadge";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "../../components/ui/dialog";
import { toast } from "sonner";
import { CreditCard, PauseCircle, Repeat, Settings } from "lucide-react";

export default function ParentPayments() {
  const [items, setItems] = useState([]);
  const [enrollments, setEnrollments] = useState([]);
  const [pauseRequests, setPauseRequests] = useState([]);
  const [busy, setBusy] = useState(null);
  const [stripeReady, setStripeReady] = useState(true);
  const [pauseFor, setPauseFor] = useState(null);
  const [pausePeriod, setPausePeriod] = useState(currentPeriod());
  const [pauseReason, setPauseReason] = useState("");
  const [params, setParams] = useSearchParams();
  const paymentPolledRef = useRef(false);
  const subscriptionPolledRef = useRef(false);

  const load = useCallback(async () => {
    const [payments, enrolls, pauses] = await Promise.all([
      api.get("/payments"),
      api.get("/enrollments"),
      api.get("/pause-requests"),
    ]);
    setItems(payments.data);
    setEnrollments(enrolls.data);
    setPauseRequests(pauses.data);
  }, []);

  useEffect(() => {
    load();
    api.get("/billing/config")
      .then(({ data }) => setStripeReady(Boolean(data.stripe_configured)))
      .catch(() => setStripeReady(false));
  }, [load]);

  const payNow = async (pid) => {
    setBusy(pid);
    try {
      const { data } = await api.post("/billing/checkout-session", {
        payment_id: pid,
        origin_url: window.location.origin,
      });
      window.location.href = data.url;
    } catch (e) {
      toast.error(formatApiError(e.response?.data?.detail));
    } finally { setBusy(null); }
  };

  const setUpAutoPay = async (enrollmentId) => {
    setBusy(`auto-${enrollmentId}`);
    try {
      const { data } = await api.post("/billing/subscription-checkout", {
        enrollment_id: enrollmentId,
        origin_url: window.location.origin,
      });
      window.location.href = data.url;
    } catch (e) {
      toast.error(formatApiError(e.response?.data?.detail));
    } finally { setBusy(null); }
  };

  const manageBilling = async () => {
    setBusy("portal");
    try {
      const { data } = await api.post("/billing/customer-portal", { origin_url: window.location.origin });
      window.location.href = data.url;
    } catch (e) {
      toast.error(formatApiError(e.response?.data?.detail));
    } finally { setBusy(null); }
  };

  const requestPause = async () => {
    setBusy(`pause-${pauseFor.id}`);
    try {
      await api.post("/pause-requests", {
        enrollment_id: pauseFor.id,
        period: pausePeriod,
        reason: pauseReason,
      });
      toast.success("Pause request sent for admin approval");
      setPauseFor(null);
      setPauseReason("");
      load();
    } catch (e) {
      toast.error(formatApiError(e.response?.data?.detail));
    } finally { setBusy(null); }
  };

  // If user returned from Stripe Checkout, poll status for up to ~30s
  useEffect(() => {
    const sid = params.get("stripe_session_id");
    if (!sid || paymentPolledRef.current) return;
    paymentPolledRef.current = true;
    let attempts = 0;
    const t = setInterval(async () => {
      attempts++;
      try {
        const { data } = await api.get(`/billing/checkout-status/${sid}`);
        if (data.payment_status === "paid") {
          clearInterval(t);
          toast.success("Payment received — thank you!");
          params.delete("stripe_session_id");
          setParams(params, { replace: true });
          load();
        } else if (data.status === "expired") {
          clearInterval(t);
          toast.error("Checkout expired");
        } else if (attempts > 10) {
          clearInterval(t);
        }
      } catch { /* */ }
    }, 3000);
    return () => clearInterval(t);
  }, [params, setParams, load]);

  useEffect(() => {
    const sid = params.get("stripe_subscription_session_id");
    if (!sid || subscriptionPolledRef.current) return;
    subscriptionPolledRef.current = true;
    let attempts = 0;
    const t = setInterval(async () => {
      attempts++;
      try {
        const { data } = await api.get(`/billing/checkout-status/${sid}`);
        if (data.subscription_status === "active" || data.status === "complete") {
          clearInterval(t);
          toast.success("Auto-pay is active");
          params.delete("stripe_subscription_session_id");
          setParams(params, { replace: true });
          load();
        } else if (data.status === "expired") {
          clearInterval(t);
          toast.error("Auto-pay setup expired");
        } else if (attempts > 10) {
          clearInterval(t);
        }
      } catch { /* */ }
    }, 3000);
    return () => clearInterval(t);
  }, [params, setParams, load]);

  const totalDue = items.filter((p) => p.status === "pending").reduce((s, p) => s + p.final_amount, 0);
  const activeEnrollments = enrollments.filter((e) => e.status === "active" && (e.billing_type || "Standard") === "Standard");
  const pendingPauseByEnrollment = pauseRequests.reduce((acc, p) => {
    if (p.status === "pending") acc[p.enrollment_id] = p;
    return acc;
  }, {});

  return (
    <div className="space-y-6" data-testid="parent-payments">
      <div className="flex items-end justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-3xl md:text-4xl font-display font-bold tracking-tighter text-slate-900">Payments</h1>
          <p className="text-sm text-slate-600 mt-1">Outstanding balance: <span className="font-semibold text-blue-600">{currency(totalDue)}</span></p>
        </div>
        <Button
          variant="outline"
          onClick={manageBilling}
          disabled={!stripeReady || busy === "portal"}
          title={stripeReady ? "Manage saved cards and subscriptions" : "Card payments are not configured"}
        >
          <Settings className="w-4 h-4 mr-2" />
          Billing portal
        </Button>
      </div>

      <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
        <div className="px-4 py-3 border-b border-slate-100 flex items-center justify-between gap-3">
          <div>
            <h2 className="font-semibold text-slate-900">Auto-pay</h2>
            <p className="text-xs text-slate-500 mt-0.5">Monthly tuition can be paid automatically by card. Pause requests require admin approval.</p>
          </div>
        </div>
        <table className="w-full text-sm">
          <thead className="bg-slate-50">
            <tr className="text-left text-xs uppercase tracking-[0.1em] text-slate-500">
              <th className="px-4 py-3">Student</th><th className="px-4 py-3">Session</th>
              <th className="px-4 py-3 text-right">Monthly</th><th className="px-4 py-3">Auto-pay</th>
              <th className="px-4 py-3">Pause</th><th className="px-4 py-3 text-right"></th>
            </tr>
          </thead>
          <tbody>
            {activeEnrollments.length === 0 && <tr><td colSpan={6} className="py-8 text-center text-slate-500">No active standard enrollments.</td></tr>}
            {activeEnrollments.map((e) => {
              const pendingPause = pendingPauseByEnrollment[e.id];
              const isAutoPay = e.payment_mode === "autopay";
              return (
                <tr key={e.id} className="border-b border-slate-100 hover:bg-slate-50">
                  <td className="px-4 py-3 font-medium text-slate-900">{e.student?.first_name} {e.student?.last_name}</td>
                  <td className="px-4 py-3 text-slate-700">{e.session?.name}</td>
                  <td className="px-4 py-3 text-right font-semibold text-blue-600">{currency(e.session?.monthly_price)}</td>
                  <td className="px-4 py-3">
                    <StatusBadge status={isAutoPay ? (e.subscription_status || "autopay") : (e.payment_mode || "manual")} />
                  </td>
                  <td className="px-4 py-3 text-xs text-slate-600">
                    {pendingPause ? <span>Pending for {pendingPause.period}</span> : (e.skip_periods || []).length ? <span>Paused: {e.skip_periods.join(", ")}</span> : "None"}
                  </td>
                  <td className="px-4 py-3 text-right space-x-2 whitespace-nowrap">
                    {!isAutoPay && (
                      <Button
                        size="sm"
                        onClick={() => setUpAutoPay(e.id)}
                        disabled={!stripeReady || busy === `auto-${e.id}`}
                        className="bg-blue-600 hover:bg-blue-500 text-white"
                      >
                        <Repeat className="w-3.5 h-3.5 mr-1.5" />
                        {busy === `auto-${e.id}` ? "..." : "Set up"}
                      </Button>
                    )}
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => { setPauseFor(e); setPausePeriod(currentPeriod()); }}
                      disabled={Boolean(pendingPause)}
                    >
                      <PauseCircle className="w-3.5 h-3.5 mr-1.5" />
                      Pause
                    </Button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-slate-50">
            <tr className="text-left text-xs uppercase tracking-[0.1em] text-slate-500">
              <th className="px-4 py-3">Period</th><th className="px-4 py-3">Student</th><th className="px-4 py-3">Session</th>
              <th className="px-4 py-3 text-right">Amount</th><th className="px-4 py-3">Status</th>
              <th className="px-4 py-3">Paid on</th><th className="px-4 py-3 text-right"></th>
            </tr>
          </thead>
          <tbody>
            {items.length === 0 && <tr><td colSpan={7} className="py-10 text-center text-slate-500">No payments yet.</td></tr>}
            {items.map((p) => (
              <tr key={p.id} className="border-b border-slate-100 hover:bg-slate-50">
                <td className="px-4 py-3 font-mono text-xs">{p.period}</td>
                <td className="px-4 py-3 font-medium text-slate-900">{p.student_name}</td>
                <td className="px-4 py-3 text-slate-700">{p.session_name}</td>
                <td className="px-4 py-3 text-right font-semibold text-blue-600">{currency(p.final_amount)}</td>
                <td className="px-4 py-3"><StatusBadge status={p.status} /></td>
                <td className="px-4 py-3 text-xs text-slate-500">{p.payment_date ? formatDate(p.payment_date) : "—"}</td>
                <td className="px-4 py-3 text-right">
                  {p.status === "pending" && (
                    <Button
                      size="sm"
                      onClick={() => payNow(p.id)}
                      disabled={busy === p.id || !stripeReady}
                      title={stripeReady ? "Pay by card" : "Card payments are not configured"}
                      data-testid={`pay-now-${p.id}`}
                      className="bg-blue-600 hover:bg-blue-500 text-white disabled:bg-slate-300 disabled:text-slate-600"
                    >
                      <CreditCard className="w-3.5 h-3.5 mr-1.5" />
                      {busy === p.id ? "..." : "Pay now"}
                    </Button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="text-xs text-slate-500">
        {stripeReady ? "Pay by card (Stripe) or at the front desk. After paying, your status updates automatically." : "Card payments are not configured yet. Please pay at the front desk."}
      </div>

      <Dialog open={!!pauseFor} onOpenChange={(v) => !v && setPauseFor(null)}>
        <DialogContent>
          <DialogHeader><DialogTitle className="font-display tracking-tight">Request a pause</DialogTitle></DialogHeader>
          <div className="space-y-3">
            <div className="text-sm text-slate-600">
              Request a one-month pause for <span className="font-medium">{pauseFor?.session?.name}</span>. Admin will approve or decline before billing changes.
            </div>
            <div>
              <label className="text-sm text-slate-700">Month to pause</label>
              <Input type="month" value={pausePeriod} onChange={(e) => setPausePeriod(e.target.value)} className="mt-1" />
            </div>
            <div>
              <label className="text-sm text-slate-700">Reason</label>
              <Input value={pauseReason} onChange={(e) => setPauseReason(e.target.value)} placeholder="Optional" className="mt-1" />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setPauseFor(null)}>Cancel</Button>
            <Button onClick={requestPause} className="bg-blue-600 hover:bg-blue-500 text-white" disabled={busy === `pause-${pauseFor?.id}`}>Send request</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
