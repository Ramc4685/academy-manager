import { useEffect, useState, useCallback, useRef } from "react";
import { useSearchParams } from "react-router-dom";
import { api, formatApiError, currency, formatDate } from "../../lib/api";
import StatusBadge from "../../components/StatusBadge";
import { Button } from "../../components/ui/button";
import { toast } from "sonner";
import { CreditCard } from "lucide-react";

export default function ParentPayments() {
  const [items, setItems] = useState([]);
  const [busy, setBusy] = useState(null);
  const [stripeReady, setStripeReady] = useState(true);
  const [params, setParams] = useSearchParams();
  const polledRef = useRef(false);

  const load = useCallback(async () => {
    const { data } = await api.get("/payments");
    setItems(data);
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

  // If user returned from Stripe Checkout, poll status for up to ~30s
  useEffect(() => {
    const sid = params.get("stripe_session_id");
    if (!sid || polledRef.current) return;
    polledRef.current = true;
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

  const totalDue = items.filter((p) => p.status === "pending").reduce((s, p) => s + p.final_amount, 0);

  return (
    <div className="space-y-6" data-testid="parent-payments">
      <div className="flex items-end justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-3xl md:text-4xl font-display font-bold tracking-tighter text-slate-900">Payments</h1>
          <p className="text-sm text-slate-600 mt-1">Outstanding balance: <span className="font-semibold text-blue-600">{currency(totalDue)}</span></p>
        </div>
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
    </div>
  );
}
