import { useEffect, useState } from "react";
import { api, formatApiError, currency, formatDate } from "../../lib/api";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "../../components/ui/select";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "../../components/ui/dialog";
import StatusBadge from "../../components/StatusBadge";
import { toast } from "sonner";
import { Plus, Trash2 } from "lucide-react";

const CATEGORIES = ["Court rental", "Equipment", "Shuttlecocks", "Software", "Marketing", "Miscellaneous", "Coach Payout"];

const empty = { category: "Court rental", description: "", amount: 0, date: new Date().toISOString().slice(0, 10), paid_to: "", status: "paid", notes: "" };

export default function AdminExpenses() {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState(empty);

  const load = async () => {
    setLoading(true);
    const { data } = await api.get("/expenses");
    setItems(data); setLoading(false);
  };
  useEffect(() => { load(); }, []);

  const save = async () => {
    try {
      await api.post("/expenses", { ...form, amount: Number(form.amount) });
      toast.success("Expense added"); setOpen(false); setForm(empty); load();
    } catch (e) {
      toast.error(formatApiError(e.response?.data?.detail));
    }
  };

  const del = async (id) => {
    if (!confirm("Delete this expense?")) return;
    await api.delete(`/expenses/${id}`); toast.success("Deleted"); load();
  };

  const total = items.reduce((s, i) => s + (i.amount || 0), 0);

  return (
    <div className="space-y-6" data-testid="admin-expenses">
      <div className="flex items-end justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-3xl md:text-4xl font-display font-bold tracking-tighter text-slate-900">Expenses</h1>
          <p className="text-sm text-slate-600 mt-1">Total tracked: <span className="font-semibold text-slate-900">{currency(total)}</span></p>
        </div>
        <Button onClick={() => { setForm(empty); setOpen(true); }} data-testid="add-expense-button" className="bg-blue-600 hover:bg-blue-500 text-white"><Plus className="w-4 h-4 mr-1.5" /> Add expense</Button>
      </div>

      <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-slate-50">
            <tr className="text-left text-xs uppercase tracking-[0.1em] text-slate-500">
              <th className="px-4 py-3">Date</th><th className="px-4 py-3">Category</th><th className="px-4 py-3">Description</th>
              <th className="px-4 py-3">Paid to</th><th className="px-4 py-3 text-right">Amount</th>
              <th className="px-4 py-3">Status</th><th className="px-4 py-3"></th>
            </tr>
          </thead>
          <tbody>
            {loading && <tr><td colSpan={7} className="py-10 text-center text-slate-500">Loading…</td></tr>}
            {!loading && items.length === 0 && <tr><td colSpan={7} className="py-10 text-center text-slate-500">No expenses yet.</td></tr>}
            {items.map((e) => (
              <tr key={e.id} className="border-b border-slate-100 hover:bg-slate-50">
                <td className="px-4 py-3 text-slate-700">{formatDate(e.date)}</td>
                <td className="px-4 py-3 font-medium text-slate-900">{e.category}</td>
                <td className="px-4 py-3 text-slate-700">{e.description}</td>
                <td className="px-4 py-3 text-slate-700">{e.paid_to || "—"}</td>
                <td className="px-4 py-3 text-right font-semibold">{currency(e.amount)}</td>
                <td className="px-4 py-3"><StatusBadge status={e.status} /></td>
                <td className="px-4 py-3 text-right"><button onClick={() => del(e.id)} className="p-1.5 hover:bg-slate-100 rounded text-red-600"><Trash2 className="w-4 h-4" /></button></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader><DialogTitle className="font-display tracking-tight">Add expense</DialogTitle></DialogHeader>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <Label>Category</Label>
              <Select value={form.category} onValueChange={(v) => setForm({ ...form, category: v })}>
                <SelectTrigger className="mt-1" data-testid="expense-category"><SelectValue /></SelectTrigger>
                <SelectContent>{CATEGORIES.map((c) => <SelectItem key={c} value={c}>{c}</SelectItem>)}</SelectContent>
              </Select>
            </div>
            <div><Label>Amount ($)</Label><Input type="number" value={form.amount} onChange={(e) => setForm({ ...form, amount: e.target.value })} className="mt-1" data-testid="expense-amount" /></div>
            <div className="col-span-2"><Label>Description</Label><Input value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} className="mt-1" data-testid="expense-description" /></div>
            <div><Label>Date</Label><Input type="date" value={form.date} onChange={(e) => setForm({ ...form, date: e.target.value })} className="mt-1" /></div>
            <div><Label>Paid to</Label><Input value={form.paid_to} onChange={(e) => setForm({ ...form, paid_to: e.target.value })} className="mt-1" /></div>
            <div>
              <Label>Status</Label>
              <Select value={form.status} onValueChange={(v) => setForm({ ...form, status: v })}>
                <SelectTrigger className="mt-1"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="paid">Paid</SelectItem>
                  <SelectItem value="pending">Pending</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="col-span-2"><Label>Notes</Label><Input value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} className="mt-1" /></div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setOpen(false)}>Cancel</Button>
            <Button onClick={save} className="bg-blue-600 hover:bg-blue-500 text-white" data-testid="save-expense">Save</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
