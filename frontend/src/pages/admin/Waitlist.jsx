import { useEffect, useState } from "react";
import { api, formatApiError, formatDateTime } from "../../lib/api";
import { Button } from "../../components/ui/button";
import StatusBadge from "../../components/StatusBadge";
import { toast } from "sonner";

export default function AdminWaitlist() {
  const [items, setItems] = useState([]);
  const [busy, setBusy] = useState("");

  const load = async () => {
    const { data } = await api.get("/waitlist");
    setItems(data);
  };

  useEffect(() => { load(); }, []);

  const enroll = async (id) => {
    setBusy(id);
    try {
      await api.post(`/waitlist/${id}/enroll`);
      toast.success("Waitlist entry enrolled");
      load();
    } catch (e) {
      toast.error(formatApiError(e.response?.data?.detail));
    } finally {
      setBusy("");
    }
  };

  return (
    <div className="space-y-6" data-testid="admin-waitlist">
      <div>
        <h1 className="text-3xl md:text-4xl font-display font-bold tracking-tighter text-slate-900">Waitlist</h1>
        <p className="text-sm text-slate-600 mt-1">Students waiting for full sessions and offered seats.</p>
      </div>
      <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-slate-50 text-slate-600">
            <tr>
              <th className="text-left p-3">Student</th>
              <th className="text-left p-3">Session</th>
              <th className="text-left p-3">Parent</th>
              <th className="text-left p-3">Status</th>
              <th className="text-left p-3">Requested</th>
              <th className="text-right p-3">Action</th>
            </tr>
          </thead>
          <tbody>
            {items.length === 0 && (
              <tr><td colSpan={6} className="p-8 text-center text-slate-500">No waitlist entries.</td></tr>
            )}
            {items.map((item) => (
              <tr key={item.id} className="border-t border-slate-100">
                <td className="p-3 font-medium text-slate-900">{item.student_name}</td>
                <td className="p-3 text-slate-700">{item.session_name}</td>
                <td className="p-3 text-slate-600">{item.parent?.name || item.parent?.email}</td>
                <td className="p-3"><StatusBadge status={item.status} /></td>
                <td className="p-3 text-slate-500">{formatDateTime(item.requested_at)}</td>
                <td className="p-3 text-right">
                  {["waiting", "offered"].includes(item.status) && (
                    <Button size="sm" variant="outline" disabled={busy === item.id} onClick={() => enroll(item.id)}>
                      Enroll
                    </Button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
