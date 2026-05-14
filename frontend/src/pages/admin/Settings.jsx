import { useEffect, useState } from "react";
import { api, formatApiError } from "../../lib/api";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import { Textarea } from "../../components/ui/textarea";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "../../components/ui/select";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "../../components/ui/tabs";
import { toast } from "sonner";
import { Send, Clock, Play } from "lucide-react";

export default function AdminSettings() {
  const [settings, setSettings] = useState(null);
  const [rules, setRules] = useState([]);
  const [coaches, setCoaches] = useState([]);
  const [testEmail, setTestEmail] = useState("");
  const [schedStatus, setSchedStatus] = useState(null);
  const [nextPeriod, setNextPeriod] = useState(null);
  const [runningJob, setRunningJob] = useState("");

  const loadScheduler = async () => {
    try {
      const [s, n] = await Promise.all([
        api.get("/scheduler/status"),
        api.get("/scheduler/next-period"),
      ]);
      setSchedStatus(s.data);
      setNextPeriod(n.data);
    } catch { /* */ }
  };

  const runMonthly = async () => {
    if (!confirm(`Generate pending invoices for ${nextPeriod?.next_period}? Existing invoices for that month will be skipped.`)) return;
    setRunningJob("invoices");
    try {
      const { data } = await api.post("/scheduler/run-monthly-invoices", { period: nextPeriod?.next_period });
      toast.success(`${data.created} invoices created • ${data.skipped} already existed • ${data.skipped_autopay} autopay skipped`);
      loadScheduler();
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
    finally { setRunningJob(""); }
  };

  const runReminders = async () => {
    if (!confirm("Run dues reminder cron now? This emails every parent with pending invoices.")) return;
    setRunningJob("reminders");
    try {
      const { data } = await api.post("/scheduler/run-dues-reminders");
      toast.success(`${data.sent} reminders sent • ${data.failed} failed • ${data.skipped} skipped`);
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
    finally { setRunningJob(""); }
  };

  const load = async () => {
    const [s, r, c] = await Promise.all([
      api.get("/settings"),
      api.get("/payout-rules"),
      api.get("/users?role=coach"),
    ]);
    setSettings(s.data); setRules(r.data); setCoaches(c.data);
  };
  useEffect(() => { load(); loadScheduler(); }, []);

  const saveSettings = async () => {
    try {
      await api.patch("/settings", settings);
      toast.success("Settings saved");
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
  };

  const setBasis = async (coach_id, basis) => {
    try {
      await api.post("/settings/payout-basis", { coach_id, basis });
      toast.success("Payout basis updated");
      load();
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
  };

  const sendTest = async () => {
    try {
      await api.post("/email/test", { to: testEmail });
      toast.success("Test email sent (check your inbox)");
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
  };

  const sendReminders = async () => {
    if (!confirm("Send dues reminder emails to ALL parents with pending payments?")) return;
    try {
      const { data } = await api.post("/email/send-dues-reminders", {});
      toast.success(`${data.sent} reminders sent`);
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
  };

  if (!settings) return <div className="text-slate-500 text-sm">Loading…</div>;

  const coachName = (id) => coaches.find((c) => c.id === id)?.name || coaches.find((c) => c.id === id)?.email || "Unknown";

  return (
    <div className="space-y-6" data-testid="admin-settings">
      <div>
        <h1 className="text-3xl md:text-4xl font-display font-bold tracking-tighter text-slate-900">Academy Settings</h1>
        <p className="text-sm text-slate-600 mt-1">Configure pricing, payouts, reminders, and email</p>
      </div>

      <Tabs defaultValue="academy">
        <TabsList>
          <TabsTrigger value="academy" data-testid="tab-academy">Academy</TabsTrigger>
          <TabsTrigger value="payouts" data-testid="tab-payouts">Payout Basis</TabsTrigger>
          <TabsTrigger value="email" data-testid="tab-email">Email</TabsTrigger>
          <TabsTrigger value="scheduler" data-testid="tab-scheduler">Automation</TabsTrigger>
        </TabsList>

        <TabsContent value="academy">
          <div className="bg-white border border-slate-200 rounded-xl p-6 grid grid-cols-2 gap-4 max-w-3xl">
            <div className="col-span-2"><Label>Academy name</Label><Input value={settings.name || ""} onChange={(e) => setSettings({ ...settings, name: e.target.value })} data-testid="academy-name" className="mt-1" /></div>
            <div><Label>Zelle handle / phone</Label><Input value={settings.zelle_handle || ""} onChange={(e) => setSettings({ ...settings, zelle_handle: e.target.value })} data-testid="zelle-handle" className="mt-1" /></div>
            <div><Label>Default session capacity</Label><Input type="number" value={settings.default_capacity || 0} onChange={(e) => setSettings({ ...settings, default_capacity: Number(e.target.value) })} className="mt-1" /></div>
            <div><Label>Beginner price ($)</Label><Input type="number" value={settings.beginner_price || 0} onChange={(e) => setSettings({ ...settings, beginner_price: Number(e.target.value) })} className="mt-1" /></div>
            <div><Label>Intermediate price ($)</Label><Input type="number" value={settings.intermediate_price || 0} onChange={(e) => setSettings({ ...settings, intermediate_price: Number(e.target.value) })} className="mt-1" /></div>
            <div><Label>Advanced price ($)</Label><Input type="number" value={settings.advanced_price || 0} onChange={(e) => setSettings({ ...settings, advanced_price: Number(e.target.value) })} className="mt-1" /></div>
            <div className="col-span-2"><Label>Reminder template (variables: {`{parent_name}, {kid_names}, {amount}, {zelle_handle}`})</Label><Textarea rows={3} value={settings.reminder_template || ""} onChange={(e) => setSettings({ ...settings, reminder_template: e.target.value })} className="mt-1 font-mono text-xs" /></div>
            <div className="col-span-2"><Button onClick={saveSettings} data-testid="save-settings" className="bg-blue-600 hover:bg-blue-500 text-white">Save settings</Button></div>
          </div>
        </TabsContent>

        <TabsContent value="payouts">
          <div className="bg-white border border-slate-200 rounded-xl p-6">
            <h3 className="font-display font-semibold tracking-tight text-slate-900 mb-3">Payout basis per coach</h3>
            <p className="text-sm text-slate-600 mb-4">Choose whether each coach is paid on <strong>collected</strong> revenue (received in cash/Stripe) or <strong>expected</strong> revenue (billed regardless of collection).</p>
            <table className="w-full text-sm">
              <thead><tr className="text-left text-xs uppercase tracking-[0.1em] text-slate-500">
                <th className="py-2">Coach</th><th className="py-2">Rule</th><th className="py-2">Basis</th>
              </tr></thead>
              <tbody>
                {rules.length === 0 && <tr><td colSpan={3} className="py-6 text-center text-slate-500">No payout rules. Set them on the Coach Payouts page.</td></tr>}
                {rules.map((r) => (
                  <tr key={r.id} className="border-b border-slate-100">
                    <td className="py-3 font-medium text-slate-900">{coachName(r.coach_id)}</td>
                    <td className="py-3 text-slate-700">{r.rule_type?.replace(/_/g, " ")} @ {r.value}{r.rule_type === "revenue_percentage" ? "%" : ""}</td>
                    <td className="py-3">
                      {r.rule_type === "revenue_percentage" ? (
                        <Select value={r.basis || "collected"} onValueChange={(v) => setBasis(r.coach_id, v)}>
                          <SelectTrigger className="w-44" data-testid={`basis-${r.coach_id}`}><SelectValue /></SelectTrigger>
                          <SelectContent>
                            <SelectItem value="collected">Collected revenue</SelectItem>
                            <SelectItem value="expected">Expected revenue</SelectItem>
                          </SelectContent>
                        </Select>
                      ) : (
                        <span className="text-xs text-slate-500">N/A for this rule type</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </TabsContent>

        <TabsContent value="email">
          <div className="bg-white border border-slate-200 rounded-xl p-6 max-w-2xl space-y-4">
            <div>
              <div className="font-display font-semibold tracking-tight text-slate-900">Email delivery (Resend)</div>
              <p className="text-sm text-slate-600 mt-1">Send a test email to confirm Resend is wired correctly.</p>
            </div>
            <div className="flex gap-2 items-end">
              <div className="flex-1">
                <Label>Send test email to</Label>
                <Input type="email" placeholder="blnobadminton@gmail.com" value={testEmail} onChange={(e) => setTestEmail(e.target.value)} className="mt-1" data-testid="test-email-input" />
              </div>
              <Button onClick={sendTest} disabled={!testEmail} data-testid="send-test-email" className="bg-blue-600 hover:bg-blue-500 text-white"><Send className="w-4 h-4 mr-1.5" /> Send test</Button>
            </div>
            <div className="text-xs text-slate-500">⚠️ In Resend test mode you can only deliver to your own verified address. Verify a domain at <a href="https://resend.com/domains" className="text-blue-600 underline" target="_blank" rel="noreferrer">resend.com/domains</a> to send to all parents.</div>
            <hr className="border-slate-200" />
            <div>
              <div className="font-display font-semibold tracking-tight text-slate-900">Bulk dues reminders</div>
              <p className="text-sm text-slate-600 mt-1">Email all parents currently on your dues followup list.</p>
              <Button onClick={sendReminders} data-testid="send-dues-reminders" className="mt-3 bg-amber-500 hover:bg-amber-400 text-white"><Send className="w-4 h-4 mr-1.5" /> Send dues reminders to all</Button>
            </div>
          </div>
        </TabsContent>

        <TabsContent value="scheduler">
          <div className="bg-white border border-slate-200 rounded-xl p-6 max-w-3xl space-y-6" data-testid="scheduler-panel">
            <div>
              <div className="flex items-center gap-2">
                <Clock className="w-5 h-5 text-blue-600" />
                <div className="font-display font-semibold tracking-tight text-slate-900 text-lg">Monthly automation</div>
              </div>
              <p className="text-sm text-slate-600 mt-1">
                Two cron jobs run automatically on your server. You can also trigger either one manually below.
              </p>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div className="border border-slate-200 rounded-xl p-4">
                <div className="text-xs uppercase tracking-[0.18em] text-slate-500">1st of month · 09:00 UTC</div>
                <div className="font-display font-semibold tracking-tight text-slate-900 mt-1">Generate monthly invoices</div>
                <div className="text-xs text-slate-500 mt-1">
                  Next run: <strong className="text-slate-700">
                    {schedStatus?.jobs?.find((j) => j.id === "monthly_invoices")?.next_run_time?.replace("T", " ").slice(0, 16) || "—"}
                  </strong>
                </div>
                <div className="text-xs text-slate-500 mt-0.5">
                  Target period: <strong className="text-slate-700">{nextPeriod?.next_period || "—"}</strong>
                </div>
                <Button
                  onClick={runMonthly}
                  disabled={runningJob === "invoices"}
                  data-testid="run-monthly-invoices"
                  className="mt-3 bg-blue-600 hover:bg-blue-500 text-white w-full"
                >
                  <Play className="w-4 h-4 mr-1.5" />
                  {runningJob === "invoices" ? "Generating…" : `Run now (${nextPeriod?.next_period || ""})`}
                </Button>
              </div>

              <div className="border border-slate-200 rounded-xl p-4">
                <div className="text-xs uppercase tracking-[0.18em] text-slate-500">5th of month · 09:00 UTC</div>
                <div className="font-display font-semibold tracking-tight text-slate-900 mt-1">Send dues reminders</div>
                <div className="text-xs text-slate-500 mt-1">
                  Next run: <strong className="text-slate-700">
                    {schedStatus?.jobs?.find((j) => j.id === "dues_reminders")?.next_run_time?.replace("T", " ").slice(0, 16) || "—"}
                  </strong>
                </div>
                <div className="text-xs text-slate-500 mt-0.5">
                  Emails every parent on the dues-followup list via Resend.
                </div>
                <Button
                  onClick={runReminders}
                  disabled={runningJob === "reminders"}
                  data-testid="run-dues-reminders-now"
                  className="mt-3 bg-amber-500 hover:bg-amber-400 text-white w-full"
                >
                  <Play className="w-4 h-4 mr-1.5" />
                  {runningJob === "reminders" ? "Sending…" : "Run now"}
                </Button>
              </div>
            </div>

            <div className="text-xs text-slate-500">
              Scheduler status: <strong className={schedStatus?.running ? "text-emerald-600" : "text-red-600"}>
                {schedStatus?.running ? "running" : "stopped"}
              </strong> · timezone <strong className="text-slate-700">{schedStatus?.timezone}</strong>
              {" "}— override defaults via env: <code className="text-[11px]">SCHEDULER_INVOICE_DAY</code>,
              {" "}<code className="text-[11px]">SCHEDULER_REMINDER_DAY</code>, etc.
            </div>
          </div>
        </TabsContent>
      </Tabs>
    </div>
  );
}
