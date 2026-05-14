import { useCallback, useEffect, useState } from "react";
import { api, formatApiError, currency, formatDate, currentPeriod } from "../../lib/api";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "../../components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "../../components/ui/select";
import StatusBadge from "../../components/StatusBadge";
import { toast } from "sonner";
import { Plus, Check, Percent } from "lucide-react";

export default function AdminPayments() {
  const [items, setItems] = useState([]);
  const [filter, setFilter] = useState("all");
  const [loading, setLoading] = useState(true);
  const [period, setPeriod] = useState(currentPeriod());
  const [genOpen, setGenOpen] = useState(false);
  const [discOpen, setDiscOpen] = useState(null);
  const [discValue, setDiscValue] = useState(0);
  const [payOpen, setPayOpen] = useState(null);
  const [payForm, setPayForm] = useState({ payment_method: "cash", notes: "" });
  const [refundOpen, setRefundOpen] = useState(null);
  const [refundForm, setRefundForm] = useState({ amount: "", reason: "" });

  const load = useCallback(async () => {
    setLoading(true);
    const q = filter === "all" ? "" : `?status=${filter}`;
    const { data } = await api.get(`/payments${q}`);
    setItems(data);
    setLoading(false);
  }, [filter]);
  useEffect(() => { load(); }, [load]);

  const generate = async () => {
    try {
      const { data } = await api.post("/payments/generate-monthly", { period });
      toast.success(`Generated ${data.created} payments (${data.skipped} already existed)`);
      setGenOpen(false); load();
    } catch (e) {
      toast.error(formatApiError(e.response?.data?.detail));
    }
  };

  const markPaid = async () => {
    try {
      await api.patch(`/payments/${payOpen}/mark-paid`, payForm);
      toast.success("Payment marked paid");
      setPayOpen(null); load();
    } catch (e) {
      toast.error(formatApiError(e.response?.data?.detail));
    }
  };

  const applyDiscount = async () => {
    try {
      await api.patch(`/payments/${discOpen}/apply-discount`, { discount: Number(discValue) });
      toast.success("Discount applied");
      setDiscOpen(null); load();
    } catch (e) {
      toast.error(formatApiError(e.response?.data?.detail));
    }
  };

  const undoPaid = async (id) => {
    if (!confirm("Revert this payment to pending?")) return;
    try {
      await api.post(`/payments/${id}/undo-paid`);
      toast.success("Payment reverted to pending");
      load();
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
  };

  const refund = async () => {
    try {
      const body = {
        amount: refundForm.amount ? Number(refundForm.amount) : null,
        reason: refundForm.reason,
      };
      await api.post(`/payments/${refundOpen}/refund`, body);
      toast.success("Refund recorded");
      setRefundOpen(null); load();
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
  };

  return (
    <div className="space-y-6" data-testid="admin-payments">
      <div className="flex items-end justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-3xl md:text-4xl font-display font-bold tracking-tighter text-slate-900">Payments</h1>
          <p className="text-sm text-slate-600 mt-1">Track monthly fees, discounts, and receipts</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Select value={filter} onValueChange={setFilter}>
            <SelectTrigger className="w-40" data-testid="payments-filter"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All statuses</SelectItem>
              <SelectItem value="pending">Pending</SelectItem>
              <SelectItem value="paid">Paid</SelectItem>
              <SelectItem value="failed">Failed</SelectItem>
            </SelectContent>
          </Select>
          <Button onClick={() => setGenOpen(true)} data-testid="generate-monthly-button" className="bg-blue-600 hover:bg-blue-500 text-white">
            <Plus className="w-4 h-4 mr-1.5" /> Generate monthly
          </Button>
        </div>
      </div>

      <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-slate-50">
            <tr className="text-left text-xs uppercase tracking-[0.1em] text-slate-500">
              <th className="px-4 py-3">Period</th><th className="px-4 py-3">Student</th><th className="px-4 py-3">Session</th>
              <th className="px-4 py-3 text-right">Amount</th><th className="px-4 py-3 text-right">Discount</th>
              <th className="px-4 py-3 text-right">Final</th><th className="px-4 py-3">Invoice</th><th className="px-4 py-3">Status</th><th className="px-4 py-3 text-right">Actions</th>
            </tr>
          </thead>
          <tbody>
            {loading && <tr><td colSpan={9} className="py-10 text-center text-slate-500">Loading…</td></tr>}
            {!loading && items.length === 0 && <tr><td colSpan={9} className="py-10 text-center text-slate-500">No payments. Click "Generate monthly" to create from active enrollments.</td></tr>}
            {items.map((p) => (
              <tr key={p.id} className="border-b border-slate-100 hover:bg-slate-50">
                <td className="px-4 py-3 font-mono text-xs">{p.period}</td>
                <td className="px-4 py-3 font-medium text-slate-900">{p.student_name}</td>
                <td className="px-4 py-3 text-slate-700">{p.session_name}</td>
                <td className="px-4 py-3 text-right">{currency(p.amount)}</td>
                <td className="px-4 py-3 text-right text-amber-700">{p.discount ? `−${currency(p.discount)}` : "—"}</td>
                <td className="px-4 py-3 text-right font-semibold text-blue-600">{currency(p.final_amount)}</td>
                <td className="px-4 py-3 font-mono text-[11px] text-slate-500">{p.invoice_number || "—"}</td>
                <td className="px-4 py-3"><StatusBadge status={p.status} /></td>
                <td className="px-4 py-3 text-right whitespace-nowrap">
                  {p.status === "pending" && (
                    <>
                      <button onClick={() => { setDiscOpen(p.id); setDiscValue(p.discount || 0); }} data-testid={`discount-${p.id}`} className="text-xs px-2 py-1 rounded hover:bg-slate-100 text-amber-700"><Percent className="w-3.5 h-3.5 inline mr-1" />Discount</button>
                      <button onClick={() => { setPayOpen(p.id); setPayForm({ payment_method: "cash", notes: "" }); }} data-testid={`mark-paid-${p.id}`} className="text-xs px-2 py-1 rounded bg-emerald-50 text-emerald-700 hover:bg-emerald-100 ml-1"><Check className="w-3.5 h-3.5 inline mr-1" />Mark paid</button>
                    </>
                  )}
                  {p.status === "paid" && (
                    <>
                      <button onClick={() => { setRefundOpen(p.id); setRefundForm({ amount: "", reason: "" }); }} data-testid={`refund-${p.id}`} className="text-xs px-2 py-1 rounded bg-red-50 text-red-700 hover:bg-red-100">Refund</button>
                      <button onClick={() => undoPaid(p.id)} data-testid={`undo-paid-${p.id}`} className="text-xs px-2 py-1 rounded bg-amber-50 text-amber-700 hover:bg-amber-100 ml-1">Undo</button>
                    </>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <Dialog open={genOpen} onOpenChange={setGenOpen}>
        <DialogContent>
          <DialogHeader><DialogTitle className="font-display tracking-tight">Generate monthly payments</DialogTitle></DialogHeader>
          <div className="space-y-3">
            <p className="text-sm text-slate-600">This creates a pending payment for every active enrollment in the chosen period (skips ones that already exist).</p>
            <div>
              <Label>Period</Label>
              <Input type="month" value={period} onChange={(e) => setPeriod(e.target.value)} className="mt-1" data-testid="generate-period-input" />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setGenOpen(false)}>Cancel</Button>
            <Button onClick={generate} className="bg-blue-600 hover:bg-blue-500 text-white" data-testid="confirm-generate">Generate</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={!!refundOpen} onOpenChange={(v) => !v && setRefundOpen(null)}>
        <DialogContent>
          <DialogHeader><DialogTitle className="font-display tracking-tight">Record refund</DialogTitle></DialogHeader>
          <div className="space-y-3">
            <div><Label>Amount ($)</Label><Input type="number" value={refundForm.amount} onChange={(e) => setRefundForm({ ...refundForm, amount: e.target.value })} placeholder="Leave blank for full remaining" className="mt-1" /></div>
            <div><Label>Reason</Label><Input value={refundForm.reason} onChange={(e) => setRefundForm({ ...refundForm, reason: e.target.value })} className="mt-1" /></div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setRefundOpen(null)}>Cancel</Button>
            <Button onClick={refund} className="bg-blue-600 hover:bg-blue-500 text-white">Refund</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={!!payOpen} onOpenChange={(v) => !v && setPayOpen(null)}>
        <DialogContent>
          <DialogHeader><DialogTitle className="font-display tracking-tight">Mark payment received</DialogTitle></DialogHeader>
          <div className="space-y-3">
            <div>
              <Label>Method</Label>
              <Select value={payForm.payment_method} onValueChange={(v) => setPayForm({ ...payForm, payment_method: v })}>
                <SelectTrigger className="mt-1"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="cash">Cash</SelectItem>
                  <SelectItem value="bank_transfer">Bank transfer</SelectItem>
                  <SelectItem value="card">Card</SelectItem>
                  <SelectItem value="check">Check</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div><Label>Notes</Label><Input value={payForm.notes} onChange={(e) => setPayForm({ ...payForm, notes: e.target.value })} className="mt-1" /></div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setPayOpen(null)}>Cancel</Button>
            <Button onClick={markPaid} className="bg-blue-600 hover:bg-blue-500 text-white" data-testid="confirm-mark-paid">Confirm</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={!!discOpen} onOpenChange={(v) => !v && setDiscOpen(null)}>
        <DialogContent>
          <DialogHeader><DialogTitle className="font-display tracking-tight">Apply discount</DialogTitle></DialogHeader>
          <div>
            <Label>Discount amount ($)</Label>
            <Input type="number" value={discValue} onChange={(e) => setDiscValue(e.target.value)} className="mt-1" data-testid="discount-input" />
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDiscOpen(null)}>Cancel</Button>
            <Button onClick={applyDiscount} className="bg-blue-600 hover:bg-blue-500 text-white" data-testid="confirm-discount">Apply</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
