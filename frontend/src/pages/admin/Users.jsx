import { useEffect, useState } from "react";
import { api, formatApiError } from "../../lib/api";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "../../components/ui/select";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "../../components/ui/dialog";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "../../components/ui/tabs";
import StatusBadge from "../../components/StatusBadge";
import { toast } from "sonner";
import { Plus, Copy } from "lucide-react";

export default function AdminUsers() {
  const [tab, setTab] = useState("coach");
  const [coaches, setCoaches] = useState([]);
  const [parents, setParents] = useState([]);
  const [invites, setInvites] = useState([]);
  const [open, setOpen] = useState(false);
  const [inv, setInv] = useState({ email: "", role: "coach", name: "" });
  const [lastInvite, setLastInvite] = useState(null);

  const load = async () => {
    const [c, p, i] = await Promise.all([
      api.get("/users?role=coach"),
      api.get("/users?role=parent"),
      api.get("/invites"),
    ]);
    setCoaches(c.data); setParents(p.data); setInvites(i.data);
  };
  useEffect(() => { load(); }, []);

  const sendInvite = async () => {
    try {
      const { data } = await api.post("/invites", inv);
      setLastInvite(data);
      toast.success(`Invite sent to ${data.email}`);
      load();
    } catch (e) {
      toast.error(formatApiError(e.response?.data?.detail));
    }
  };

  const copyLink = (url) => {
    navigator.clipboard.writeText(url);
    toast.success("Invite link copied");
  };

  return (
    <div className="space-y-6" data-testid="admin-users">
      <div className="flex items-end justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-3xl md:text-4xl font-display font-bold tracking-tighter text-slate-900">Coaches & Parents</h1>
          <p className="text-sm text-slate-600 mt-1">Invite, view, and manage user accounts</p>
        </div>
        <Button onClick={() => { setInv({ email: "", role: tab, name: "" }); setLastInvite(null); setOpen(true); }} data-testid="invite-user-button" className="bg-blue-600 hover:bg-blue-500 text-white">
          <Plus className="w-4 h-4 mr-1.5" /> Invite {tab === "coach" ? "Coach" : "Parent"}
        </Button>
      </div>

      <Tabs value={tab} onValueChange={setTab}>
        <TabsList>
          <TabsTrigger value="coach" data-testid="tab-coaches">Coaches ({coaches.length})</TabsTrigger>
          <TabsTrigger value="parent" data-testid="tab-parents">Parents ({parents.length})</TabsTrigger>
          <TabsTrigger value="invites" data-testid="tab-invites">Pending invites ({invites.length})</TabsTrigger>
        </TabsList>

        <TabsContent value="coach">
          <UserTable users={coaches} />
        </TabsContent>
        <TabsContent value="parent">
          <UserTable users={parents} />
        </TabsContent>
        <TabsContent value="invites">
          <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
            <table className="w-full text-sm">
              <thead className="bg-slate-50">
                <tr className="text-left text-xs uppercase tracking-[0.1em] text-slate-500">
                  <th className="px-4 py-3">Email</th><th className="px-4 py-3">Role</th><th className="px-4 py-3">Status</th><th className="px-4 py-3"></th>
                </tr>
              </thead>
              <tbody>
                {invites.length === 0 && <tr><td colSpan={4} className="py-10 text-center text-slate-500">No pending invites</td></tr>}
                {invites.map((inv) => (
                  <tr key={inv.token || inv.email} className="border-b border-slate-100 hover:bg-slate-50">
                    <td className="px-4 py-3">{inv.email}</td>
                    <td className="px-4 py-3 capitalize">{inv.role}</td>
                    <td className="px-4 py-3"><StatusBadge status={inv.status} /></td>
                    <td className="px-4 py-3 text-right">
                      {inv.accept_url && (
                        <button onClick={() => copyLink(inv.accept_url)} className="text-blue-600 hover:underline text-xs flex items-center gap-1 ml-auto">
                          <Copy className="w-3.5 h-3.5" /> Copy link
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </TabsContent>
      </Tabs>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader><DialogTitle className="font-display tracking-tight">Send invitation</DialogTitle></DialogHeader>
          {!lastInvite ? (
            <div className="space-y-4">
              <div>
                <Label>Email</Label>
                <Input value={inv.email} onChange={(e) => setInv({ ...inv, email: e.target.value })} className="mt-1" data-testid="invite-email-input" />
              </div>
              <div>
                <Label>Name (optional)</Label>
                <Input value={inv.name} onChange={(e) => setInv({ ...inv, name: e.target.value })} className="mt-1" />
              </div>
              <div>
                <Label>Role</Label>
                <Select value={inv.role} onValueChange={(v) => setInv({ ...inv, role: v })}>
                  <SelectTrigger className="mt-1"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="coach">Coach</SelectItem>
                    <SelectItem value="parent">Parent</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <DialogFooter>
                <Button variant="outline" onClick={() => setOpen(false)}>Cancel</Button>
                <Button onClick={sendInvite} data-testid="send-invite-button" className="bg-blue-600 hover:bg-blue-500 text-white">Send Invite</Button>
              </DialogFooter>
            </div>
          ) : (
            <div className="space-y-4">
              <div className="text-sm text-slate-700">Share this invite link with <span className="font-semibold">{lastInvite.email}</span>:</div>
              <div className="p-3 bg-slate-50 rounded-lg text-xs font-mono break-all border border-slate-200">{lastInvite.accept_url}</div>
              <DialogFooter>
                <Button variant="outline" onClick={() => setOpen(false)}>Close</Button>
                <Button onClick={() => copyLink(lastInvite.accept_url)} className="bg-blue-600 hover:bg-blue-500 text-white"><Copy className="w-4 h-4 mr-1.5" /> Copy link</Button>
              </DialogFooter>
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}

function UserTable({ users }) {
  return (
    <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
      <table className="w-full text-sm">
        <thead className="bg-slate-50">
          <tr className="text-left text-xs uppercase tracking-[0.1em] text-slate-500">
            <th className="px-4 py-3">Name</th><th className="px-4 py-3">Email</th>
            <th className="px-4 py-3">Phone</th><th className="px-4 py-3">Status</th>
          </tr>
        </thead>
        <tbody>
          {users.length === 0 && <tr><td colSpan={4} className="py-10 text-center text-slate-500">None yet</td></tr>}
          {users.map((u) => (
            <tr key={u.id} className="border-b border-slate-100 hover:bg-slate-50">
              <td className="px-4 py-3 font-medium text-slate-900">{u.name}</td>
              <td className="px-4 py-3 text-slate-700">{u.email}</td>
              <td className="px-4 py-3 text-slate-700">{u.phone || "—"}</td>
              <td className="px-4 py-3"><StatusBadge status={u.status} /></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
