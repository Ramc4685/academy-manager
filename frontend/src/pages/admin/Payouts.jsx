import { useEffect, useState } from "react";
import { api, formatApiError, currency, currentPeriod, formatDate } from "../../lib/api";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "../../components/ui/select";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "../../components/ui/dialog";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "../../components/ui/tabs";
import StatusBadge from "../../components/StatusBadge";
import { toast } from "sonner";
import { Calculator, Check, DollarSign } from "lucide-react";

const RULE_TYPES = [
  { value: "revenue_percentage", label: "Revenue %" },
  { value: "fixed_per_class", label: "Fixed per class" },
  { value: "fixed_monthly", label: "Fixed monthly" },
  { value: "per_student", label: "Per student / month" },
];

export default function AdminPayouts() {
  const [tab, setTab] = useState("payouts");
  const [payouts, setPayouts] = useState([]);
  const [rules, setRules] = useState([]);
  const [coaches, setCoaches] = useState([]);
  const [period, setPeriod] = useState(currentPeriod());
  const [ruleOpen, setRuleOpen] = useState(false);
  const [ruleForm, setRuleForm] = useState({ coach_id: "", rule_type: "revenue_percentage", value: 30 });

  const load = async () => {
    const [p, r, c] = await Promise.all([
      api.get("/coach-payouts"),
      api.get("/payout-rules"),
      api.get("/users?role=coach"),
    ]);
    setPayouts(p.data); setRules(r.data); setCoaches(c.data);
  };
  useEffect(() => { load(); }, []);

  const calculate = async () => {
    try {
      const { data } = await api.post("/coach-payouts/calculate", { period });
      toast.success(`Calculated ${data.created} new payouts for ${period}`);
      load();
    } catch (e) {
      toast.error(formatApiError(e.response?.data?.detail));
    }
  };

  const approve = async (id) => { await api.post(`/coach-payouts/${id}/approve`); toast.success("Approved"); load(); };
  const pay = async (id) => { await api.post(`/coach-payouts/${id}/mark-paid`); toast.success("Marked paid"); load(); };
  const undoApprove = async (id) => { await api.post(`/coach-payouts/${id}/undo-approve`); toast.success("Reverted to calculated"); load(); };
  const undoPaid = async (id) => {
    if (!confirm("Revert payout to approved (and remove auto-expense)?")) return;
    await api.post(`/coach-payouts/${id}/undo-paid`); toast.success("Reverted to approved"); load();
  };

  const saveRule = async () => {
    try {
      await api.post("/payout-rules", { ...ruleForm, value: Number(ruleForm.value) });
      toast.success("Payout rule saved");
      setRuleOpen(false); load();
    } catch (e) {
      toast.error(formatApiError(e.response?.data?.detail));
    }
  };

  const coachName = (id) => coaches.find((c) => c.id === id)?.name || coaches.find((c) => c.id === id)?.email || "Unknown";

  return (
    <div className="space-y-6" data-testid="admin-payouts">
      <div className="flex items-end justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-3xl md:text-4xl font-display font-bold tracking-tighter text-slate-900">Coach Payouts</h1>
          <p className="text-sm text-slate-600 mt-1">Configure payout rules and calculate monthly amounts</p>
        </div>
      </div>

      <Tabs value={tab} onValueChange={setTab}>
        <TabsList>
          <TabsTrigger value="payouts" data-testid="tab-payouts">Payouts</TabsTrigger>
          <TabsTrigger value="rules" data-testid="tab-rules">Payout rules</TabsTrigger>
        </TabsList>

        <TabsContent value="payouts">
          <div className="flex gap-2 mb-4">
            <Input type="month" value={period} onChange={(e) => setPeriod(e.target.value)} className="w-44" data-testid="payout-period" />
            <Button onClick={calculate} data-testid="calculate-payouts-button" className="bg-blue-600 hover:bg-blue-500 text-white">
              <Calculator className="w-4 h-4 mr-1.5" /> Calculate for {period}
            </Button>
          </div>
          <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
            <table className="w-full text-sm">
              <thead className="bg-slate-50">
                <tr className="text-left text-xs uppercase tracking-[0.1em] text-slate-500">
                  <th className="px-4 py-3">Period</th><th className="px-4 py-3">Coach</th><th className="px-4 py-3">Rule</th>
                  <th className="px-4 py-3 text-right">Amount</th><th className="px-4 py-3">Status</th><th className="px-4 py-3 text-right">Actions</th>
                </tr>
              </thead>
              <tbody>
                {payouts.length === 0 && <tr><td colSpan={6} className="py-10 text-center text-slate-500">No payouts. Click "Calculate" to compute for a period.</td></tr>}
                {payouts.map((p) => (
                  <tr key={p.id} className="border-b border-slate-100 hover:bg-slate-50">
                    <td className="px-4 py-3 font-mono text-xs">{p.period}</td>
                    <td className="px-4 py-3 font-medium text-slate-900">{p.coach_name}</td>
                    <td className="px-4 py-3 text-slate-700">{p.rule_type?.replace(/_/g, " ")} ({p.rule_value})</td>
                    <td className="px-4 py-3 text-right font-semibold text-blue-600">{currency(p.calculated_amount)}</td>
                    <td className="px-4 py-3"><StatusBadge status={p.status} /></td>
                    <td className="px-4 py-3 text-right whitespace-nowrap">
                      {p.status === "calculated" && (
                        <button onClick={() => approve(p.id)} data-testid={`approve-payout-${p.id}`} className="text-xs px-2 py-1 rounded bg-amber-50 text-amber-700 hover:bg-amber-100"><Check className="w-3.5 h-3.5 inline mr-1" />Approve</button>
                      )}
                      {p.status === "approved" && (
                        <>
                          <button onClick={() => pay(p.id)} data-testid={`pay-payout-${p.id}`} className="text-xs px-2 py-1 rounded bg-emerald-50 text-emerald-700 hover:bg-emerald-100"><DollarSign className="w-3.5 h-3.5 inline mr-1" />Mark paid</button>
                          <button onClick={() => undoApprove(p.id)} className="text-xs px-2 py-1 rounded hover:bg-slate-100 text-slate-700 ml-1">Undo</button>
                        </>
                      )}
                      {p.status === "paid" && (
                        <button onClick={() => undoPaid(p.id)} data-testid={`undo-payout-${p.id}`} className="text-xs px-2 py-1 rounded bg-amber-50 text-amber-700 hover:bg-amber-100">Undo paid</button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </TabsContent>

        <TabsContent value="rules">
          <div className="flex justify-end mb-4">
            <Button onClick={() => { setRuleForm({ coach_id: "", rule_type: "revenue_percentage", value: 30 }); setRuleOpen(true); }} data-testid="add-rule-button" className="bg-blue-600 hover:bg-blue-500 text-white">Set payout rule</Button>
          </div>
          <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
            <table className="w-full text-sm">
              <thead className="bg-slate-50">
                <tr className="text-left text-xs uppercase tracking-[0.1em] text-slate-500">
                  <th className="px-4 py-3">Coach</th><th className="px-4 py-3">Rule type</th><th className="px-4 py-3 text-right">Value</th>
                </tr>
              </thead>
              <tbody>
                {rules.length === 0 && <tr><td colSpan={3} className="py-10 text-center text-slate-500">No rules. Add a payout rule for each coach.</td></tr>}
                {rules.map((r) => (
                  <tr key={r.id} className="border-b border-slate-100 hover:bg-slate-50">
                    <td className="px-4 py-3 font-medium text-slate-900">{coachName(r.coach_id)}</td>
                    <td className="px-4 py-3 capitalize">{r.rule_type.replace(/_/g, " ")}</td>
                    <td className="px-4 py-3 text-right font-semibold">{r.rule_type === "revenue_percentage" ? `${r.value}%` : currency(r.value)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </TabsContent>
      </Tabs>

      <Dialog open={ruleOpen} onOpenChange={setRuleOpen}>
        <DialogContent>
          <DialogHeader><DialogTitle className="font-display tracking-tight">Set payout rule</DialogTitle></DialogHeader>
          <div className="space-y-4">
            <div>
              <Label>Coach</Label>
              <Select value={ruleForm.coach_id} onValueChange={(v) => setRuleForm({ ...ruleForm, coach_id: v })}>
                <SelectTrigger className="mt-1" data-testid="rule-coach"><SelectValue placeholder="Select coach" /></SelectTrigger>
                <SelectContent>{coaches.map((c) => <SelectItem key={c.id} value={c.id}>{c.name || c.email}</SelectItem>)}</SelectContent>
              </Select>
            </div>
            <div>
              <Label>Rule type</Label>
              <Select value={ruleForm.rule_type} onValueChange={(v) => setRuleForm({ ...ruleForm, rule_type: v })}>
                <SelectTrigger className="mt-1" data-testid="rule-type"><SelectValue /></SelectTrigger>
                <SelectContent>{RULE_TYPES.map((t) => <SelectItem key={t.value} value={t.value}>{t.label}</SelectItem>)}</SelectContent>
              </Select>
            </div>
            <div>
              <Label>Value {ruleForm.rule_type === "revenue_percentage" ? "(%)" : "($)"}</Label>
              <Input type="number" value={ruleForm.value} onChange={(e) => setRuleForm({ ...ruleForm, value: e.target.value })} className="mt-1" data-testid="rule-value" />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setRuleOpen(false)}>Cancel</Button>
            <Button onClick={saveRule} className="bg-blue-600 hover:bg-blue-500 text-white" data-testid="save-rule">Save</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
