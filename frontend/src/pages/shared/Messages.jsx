import { useEffect, useState, useRef } from "react";
import { api, formatApiError, formatDateTime } from "../../lib/api";
import { useAuth } from "../../contexts/AuthContext";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "../../components/ui/select";
import { toast } from "sonner";
import { Send, Plus } from "lucide-react";

export default function Messages() {
  const { user } = useAuth();
  const [threads, setThreads] = useState([]);
  const [active, setActive] = useState(null);
  const [messages, setMessages] = useState([]);
  const [draft, setDraft] = useState("");
  const [contacts, setContacts] = useState([]);
  const [newOpen, setNewOpen] = useState(false);
  const [newTo, setNewTo] = useState("");
  const scrollRef = useRef(null);

  const loadThreads = async () => {
    const { data } = await api.get("/messages/threads");
    setThreads(data);
  };

  useEffect(() => { loadThreads(); }, []);

  useEffect(() => {
    // Load contacts based on role
    if (user?.role === "admin") {
      api.get("/users").then((r) => setContacts(r.data.filter((u) => u.id !== user.id)));
    } else if (user?.role === "coach") {
      // Coach: parents of students in own sessions + admins
      api.get("/users?role=admin").then((adminR) => {
        api.get("/users?role=parent").then((p) => {
          setContacts([...adminR.data, ...p.data]);
        }).catch(() => setContacts(adminR.data));
      });
    } else if (user?.role === "parent") {
      // Parent: coaches + admins
      Promise.all([api.get("/users?role=coach").catch(() => ({ data: [] })), api.get("/users?role=admin").catch(() => ({ data: [] }))])
        .then(([c, a]) => setContacts([...(c.data || []), ...(a.data || [])]));
    }
  }, [user]);

  const openThread = async (otherId) => {
    setActive(otherId);
    const { data } = await api.get(`/messages/thread/${otherId}`);
    setMessages(data);
    loadThreads();
  };

  const send = async () => {
    if (!draft.trim() || !active) return;
    try {
      await api.post("/messages", { to_user_id: active, body: draft });
      setDraft("");
      openThread(active);
    } catch (e) {
      toast.error(formatApiError(e.response?.data?.detail));
    }
  };

  useEffect(() => {
    if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
  }, [messages]);

  const startNew = () => {
    if (!newTo) return;
    setNewOpen(false);
    openThread(newTo);
  };

  const activeUser = contacts.find((c) => c.id === active) || threads.find((t) => t.other_user_id === active)?.other_user;

  return (
    <div className="h-[calc(100vh-8rem)] flex bg-white border border-slate-200 rounded-xl overflow-hidden" data-testid="messages-page">
      <aside className="w-72 border-r border-slate-200 flex flex-col">
        <div className="p-4 border-b border-slate-100 flex items-center justify-between">
          <div className="font-display font-semibold tracking-tight text-slate-900">Conversations</div>
          <button onClick={() => setNewOpen(true)} data-testid="new-message-button" className="text-blue-600 p-1.5 hover:bg-slate-100 rounded"><Plus className="w-4 h-4" /></button>
        </div>
        <div className="overflow-y-auto flex-1">
          {threads.length === 0 && <div className="p-6 text-sm text-slate-500 text-center">No conversations yet.</div>}
          {threads.map((t) => (
            <button
              key={t.other_user_id}
              onClick={() => openThread(t.other_user_id)}
              data-testid={`thread-${t.other_user_id}`}
              className={`w-full text-left p-3 border-b border-slate-100 hover:bg-slate-50 ${active === t.other_user_id ? "bg-blue-50" : ""}`}
            >
              <div className="flex items-center justify-between">
                <div className="font-medium text-slate-900 text-sm">{t.other_user.name}</div>
                {t.unread > 0 && <span className="bg-blue-600 text-white text-[10px] px-1.5 py-0.5 rounded-full font-bold">{t.unread}</span>}
              </div>
              <div className="text-xs text-slate-500 truncate mt-0.5">{t.last_message}</div>
            </button>
          ))}
        </div>
      </aside>

      <section className="flex-1 flex flex-col">
        {!active && (
          <div className="flex-1 flex items-center justify-center text-slate-500 text-sm">Select a conversation or start a new one.</div>
        )}
        {active && (
          <>
            <div className="px-4 py-3 border-b border-slate-100">
              <div className="font-display font-semibold text-slate-900 tracking-tight">{activeUser?.name || "Conversation"}</div>
              <div className="text-xs text-slate-500 capitalize">{activeUser?.role}</div>
            </div>
            <div ref={scrollRef} className="flex-1 overflow-y-auto p-4 space-y-3 bg-slate-50">
              {messages.length === 0 && <div className="text-center text-sm text-slate-500 mt-10">No messages yet. Say hi!</div>}
              {messages.map((m) => {
                const mine = m.from_user_id === user.id;
                return (
                  <div key={m.id} className={`flex ${mine ? "justify-end" : "justify-start"}`}>
                    <div className={`max-w-[75%] px-4 py-2 rounded-2xl ${mine ? "bg-blue-600 text-white rounded-br-sm" : "bg-white border border-slate-200 text-slate-900 rounded-bl-sm"}`}>
                      <div className="text-sm">{m.body}</div>
                      <div className={`text-[10px] mt-1 ${mine ? "text-blue-100" : "text-slate-400"}`}>{formatDateTime(m.created_at)}</div>
                    </div>
                  </div>
                );
              })}
            </div>
            <div className="p-3 border-t border-slate-100 flex gap-2">
              <Input value={draft} onChange={(e) => setDraft(e.target.value)} onKeyDown={(e) => e.key === "Enter" && send()} placeholder="Type a message…" data-testid="message-input" />
              <Button onClick={send} className="bg-blue-600 hover:bg-blue-500 text-white" data-testid="send-message"><Send className="w-4 h-4" /></Button>
            </div>
          </>
        )}
      </section>

      {newOpen && (
        <div className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center p-4" onClick={() => setNewOpen(false)}>
          <div className="bg-white rounded-xl p-6 w-full max-w-md" onClick={(e) => e.stopPropagation()}>
            <div className="font-display font-semibold tracking-tight text-slate-900 mb-4">Start a new conversation</div>
            <Select value={newTo} onValueChange={setNewTo}>
              <SelectTrigger data-testid="new-message-recipient"><SelectValue placeholder="Select recipient" /></SelectTrigger>
              <SelectContent>
                {contacts.map((c) => <SelectItem key={c.id} value={c.id}>{c.name || c.email} ({c.role})</SelectItem>)}
              </SelectContent>
            </Select>
            <div className="flex justify-end gap-2 mt-4">
              <Button variant="outline" onClick={() => setNewOpen(false)}>Cancel</Button>
              <Button onClick={startNew} disabled={!newTo} className="bg-blue-600 hover:bg-blue-500 text-white" data-testid="start-message">Start</Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
