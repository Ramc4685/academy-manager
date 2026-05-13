import { useEffect, useState } from "react";
import { api, currency } from "../../lib/api";
import { Input } from "../../components/ui/input";
import { Button } from "../../components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "../../components/ui/dialog";
import { Copy, MessageCircle, Phone } from "lucide-react";
import { toast } from "sonner";

export default function DuesFollowup() {
  const [items, setItems] = useState([]);
  const [filter, setFilter] = useState("");
  const [loading, setLoading] = useState(true);
  const [preview, setPreview] = useState(null);

  useEffect(() => {
    api.get("/dues-followup").then((r) => setItems(r.data)).finally(() => setLoading(false));
  }, []);

  const totalDue = items.reduce((s, i) => s + (i.total_due || 0), 0);
  const filtered = items.filter((i) => {
    if (!filter) return true;
    const t = `${i.parent_name} ${i.parent_email} ${(i.kids || []).join(" ")}`.toLowerCase();
    return t.includes(filter.toLowerCase());
  });

  const copy = (txt) => { navigator.clipboard.writeText(txt); toast.success("Message copied"); };

  return (
    <div className="space-y-6" data-testid="admin-dues">
      <div className="flex items-end justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-3xl md:text-4xl font-display font-bold tracking-tighter text-slate-900">Dues Followup</h1>
          <p className="text-sm text-slate-600 mt-1">
            <span className="font-semibold text-red-600">{items.length}</span> parents owe a total of
            <span className="font-semibold text-blue-600"> {currency(totalDue)}</span>
          </p>
        </div>
        <Input placeholder="Search parent, kid, email…" value={filter} onChange={(e) => setFilter(e.target.value)} className="w-72" data-testid="dues-search" />
      </div>

      <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-slate-50">
            <tr className="text-left text-xs uppercase tracking-[0.1em] text-slate-500">
              <th className="px-4 py-3">Parent</th><th className="px-4 py-3">Children</th>
              <th className="px-4 py-3">Phone</th><th className="px-4 py-3 text-right">Total Due</th>
              <th className="px-4 py-3 text-right">Actions</th>
            </tr>
          </thead>
          <tbody>
            {loading && <tr><td colSpan={5} className="py-10 text-center text-slate-500">Loading…</td></tr>}
            {!loading && filtered.length === 0 && <tr><td colSpan={5} className="py-10 text-center text-slate-500">🎉 No outstanding dues!</td></tr>}
            {filtered.map((r) => (
              <tr key={r.parent_id} className="border-b border-slate-100 hover:bg-slate-50">
                <td className="px-4 py-3">
                  <div className="font-medium text-slate-900">{r.parent_name}</div>
                  <div className="text-xs text-slate-500">{r.parent_email}</div>
                </td>
                <td className="px-4 py-3 text-slate-700">{(r.kids || []).join(", ")}</td>
                <td className="px-4 py-3 text-slate-700 font-mono text-xs">
                  {r.parent_phone ? (
                    <a href={`tel:${r.parent_phone}`} className="hover:underline flex items-center gap-1"><Phone className="w-3 h-3" />{r.parent_phone}</a>
                  ) : "—"}
                </td>
                <td className="px-4 py-3 text-right font-semibold text-red-600">{currency(r.total_due)}</td>
                <td className="px-4 py-3 text-right space-x-1 whitespace-nowrap">
                  <button onClick={() => setPreview(r)} data-testid={`preview-${r.parent_id}`} className="text-xs px-2 py-1 rounded hover:bg-slate-100 text-slate-700">Preview</button>
                  <button onClick={() => copy(r.message)} className="text-xs px-2 py-1 rounded hover:bg-slate-100 text-blue-600"><Copy className="w-3.5 h-3.5 inline mr-1" />Copy</button>
                  {r.whatsapp_url && (
                    <a href={r.whatsapp_url} target="_blank" rel="noreferrer" data-testid={`wa-${r.parent_id}`} className="inline-flex items-center text-xs px-2.5 py-1 rounded bg-emerald-50 text-emerald-700 hover:bg-emerald-100">
                      <MessageCircle className="w-3.5 h-3.5 mr-1" /> WhatsApp
                    </a>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <Dialog open={!!preview} onOpenChange={(v) => !v && setPreview(null)}>
        <DialogContent>
          <DialogHeader><DialogTitle className="font-display tracking-tight">Reminder preview</DialogTitle></DialogHeader>
          {preview && (
            <div className="space-y-3">
              <div className="text-sm text-slate-600">To: <span className="font-medium text-slate-900">{preview.parent_name}</span> · {preview.parent_phone || "no phone"}</div>
              <div className="p-4 rounded-xl bg-emerald-50 border border-emerald-200 text-sm text-slate-800 whitespace-pre-wrap">{preview.message}</div>
            </div>
          )}
          <DialogFooter>
            <Button variant="outline" onClick={() => setPreview(null)}>Close</Button>
            <Button onClick={() => copy(preview?.message)} className="bg-blue-600 hover:bg-blue-500 text-white"><Copy className="w-4 h-4 mr-1.5" /> Copy</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
