import { useCallback, useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { api, formatApiError, formatDate } from "../../lib/api";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import { Textarea } from "../../components/ui/textarea";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "../../components/ui/tabs";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "../../components/ui/dialog";
import StatusBadge from "../../components/StatusBadge";
import { toast } from "sonner";
import { Plus } from "lucide-react";

const ATT_STATUSES = ["present", "absent", "late", "excused"];

export default function CoachSessionDetail() {
  const { id } = useParams();
  const [session, setSession] = useState(null);
  const [roster, setRoster] = useState([]);
  const [date, setDate] = useState(new Date().toISOString().slice(0, 10));
  const [attMap, setAttMap] = useState({});
  const [savedAtt, setSavedAtt] = useState({});
  const [lessons, setLessons] = useState([]);
  const [notes, setNotes] = useState([]);
  const [lessonOpen, setLessonOpen] = useState(false);
  const [lessonForm, setLessonForm] = useState({ objective: "", warmup: "", skill_drill: "", game_activity: "", fitness_activity: "", homework: "", coach_notes: "", date: new Date().toISOString().slice(0, 10) });
  const [noteOpen, setNoteOpen] = useState(null);
  const [noteText, setNoteText] = useState("");

  const load = useCallback(async () => {
    const [s, e, l, n] = await Promise.all([
      api.get(`/sessions/${id}`),
      api.get(`/enrollments?session_id=${id}`),
      api.get(`/lesson-plans?session_id=${id}`),
      api.get(`/progress-notes`),
    ]);
    setSession(s.data); setRoster(e.data); setLessons(l.data);
    setNotes(n.data.filter((x) => !x.session_id || x.session_id === id));
  }, [id]);
  useEffect(() => { load(); }, [load]);

  // Load existing attendance for the date
  useEffect(() => {
    if (!id || !date) return;
    api.get(`/attendance?session_id=${id}&date=${date}`).then((r) => {
      const m = {};
      r.data.forEach((a) => { m[a.student_id] = a.status; });
      setSavedAtt(m);
      setAttMap(m);
    });
  }, [id, date]);

  const setStatus = (sid, status) => setAttMap({ ...attMap, [sid]: status });

  const saveAttendance = async () => {
    const items = roster
      .filter((r) => attMap[r.student_id])
      .map((r) => ({ student_id: r.student_id, status: attMap[r.student_id], notes: "" }));
    try {
      await api.post("/attendance/bulk", { session_id: id, date, items });
      toast.success(`Saved ${items.length} attendance records`);
      setSavedAtt(attMap);
    } catch (e) {
      toast.error(formatApiError(e.response?.data?.detail));
    }
  };

  const saveLesson = async () => {
    try {
      await api.post("/lesson-plans", { ...lessonForm, session_id: id });
      toast.success("Lesson plan added"); setLessonOpen(false); load();
    } catch (e) {
      toast.error(formatApiError(e.response?.data?.detail));
    }
  };

  const saveNote = async () => {
    try {
      await api.post("/progress-notes", { student_id: noteOpen, session_id: id, note: noteText });
      toast.success("Progress note added"); setNoteOpen(null); setNoteText(""); load();
    } catch (e) {
      toast.error(formatApiError(e.response?.data?.detail));
    }
  };

  if (!session) return <div className="text-slate-500 text-sm">Loading…</div>;

  return (
    <div className="space-y-6" data-testid="coach-session-detail">
      <div>
        <div className="text-xs uppercase tracking-[0.18em] text-slate-500">Session</div>
        <h1 className="text-3xl md:text-4xl font-display font-bold tracking-tighter text-slate-900">{session.name}</h1>
        <p className="text-sm text-slate-600 mt-1">{session.location} · {(session.days_of_week || []).join(", ")} · {session.start_time}–{session.end_time}</p>
      </div>

      <Tabs defaultValue="attendance">
        <TabsList>
          <TabsTrigger value="attendance" data-testid="tab-attendance">Attendance</TabsTrigger>
          <TabsTrigger value="lesson-plans" data-testid="tab-lesson-plans">Lesson plans</TabsTrigger>
          <TabsTrigger value="progress" data-testid="tab-progress">Progress notes</TabsTrigger>
        </TabsList>

        <TabsContent value="attendance">
          <div className="bg-white border border-slate-200 rounded-xl p-6 space-y-4">
            <div className="flex items-end gap-3 flex-wrap">
              <div>
                <Label>Date</Label>
                <Input type="date" value={date} onChange={(e) => setDate(e.target.value)} className="mt-1 w-44" data-testid="attendance-date" />
              </div>
              <Button onClick={saveAttendance} className="bg-blue-600 hover:bg-blue-500 text-white" data-testid="save-attendance">Save attendance</Button>
            </div>
            <div className="overflow-x-auto" data-testid="attendance-grid">
              {roster.length === 0 && <div className="text-sm text-slate-500 py-6 text-center">No students enrolled yet.</div>}
              {roster.map((e) => (
                <div key={e.id} className="flex items-center justify-between py-3 border-b border-slate-100 last:border-0 gap-4">
                  <div className="flex-1">
                    <div className="font-medium text-slate-900">{e.student?.first_name} {e.student?.last_name}</div>
                    <div className="text-xs text-slate-500">Age {e.student?.age}</div>
                  </div>
                  <div className="flex gap-1.5">
                    {ATT_STATUSES.map((s) => (
                      <button
                        key={s}
                        onClick={() => setStatus(e.student_id, s)}
                        data-testid={`att-${e.student_id}-${s}`}
                        className={`px-3 py-1.5 rounded-full text-xs font-medium border capitalize ${attMap[e.student_id] === s ? "bg-blue-600 border-blue-600 text-white" : "bg-white border-slate-200 text-slate-700 hover:bg-slate-50"}`}
                      >
                        {s[0].toUpperCase()}
                      </button>
                    ))}
                  </div>
                  <button onClick={() => { setNoteOpen(e.student_id); setNoteText(""); }} data-testid={`add-note-${e.student_id}`} className="text-xs text-blue-600 hover:underline whitespace-nowrap">+ Note</button>
                </div>
              ))}
            </div>
          </div>
        </TabsContent>

        <TabsContent value="lesson-plans">
          <div className="flex justify-end mb-4">
            <Button onClick={() => setLessonOpen(true)} data-testid="add-lesson-button" className="bg-blue-600 hover:bg-blue-500 text-white"><Plus className="w-4 h-4 mr-1.5" /> New plan</Button>
          </div>
          <div className="space-y-3">
            {lessons.length === 0 && <div className="bg-white border border-slate-200 rounded-xl p-6 text-sm text-slate-500 text-center">No lesson plans yet.</div>}
            {lessons.map((l) => (
              <div key={l.id} className="bg-white border border-slate-200 rounded-xl p-6">
                <div className="flex justify-between items-start">
                  <div className="font-display font-semibold text-slate-900 tracking-tight">{l.objective}</div>
                  <span className="text-xs text-slate-500">{formatDate(l.date)}</span>
                </div>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-3 mt-3 text-sm">
                  {l.warmup && <div><span className="text-xs uppercase tracking-[0.1em] text-slate-500 block">Warmup</span><div className="text-slate-700">{l.warmup}</div></div>}
                  {l.skill_drill && <div><span className="text-xs uppercase tracking-[0.1em] text-slate-500 block">Skill drill</span><div className="text-slate-700">{l.skill_drill}</div></div>}
                  {l.game_activity && <div><span className="text-xs uppercase tracking-[0.1em] text-slate-500 block">Game</span><div className="text-slate-700">{l.game_activity}</div></div>}
                  {l.fitness_activity && <div><span className="text-xs uppercase tracking-[0.1em] text-slate-500 block">Fitness</span><div className="text-slate-700">{l.fitness_activity}</div></div>}
                  {l.homework && <div className="md:col-span-2"><span className="text-xs uppercase tracking-[0.1em] text-slate-500 block">Homework</span><div className="text-slate-700">{l.homework}</div></div>}
                  {l.coach_notes && <div className="md:col-span-2"><span className="text-xs uppercase tracking-[0.1em] text-slate-500 block">Coach notes</span><div className="text-slate-700">{l.coach_notes}</div></div>}
                </div>
              </div>
            ))}
          </div>
        </TabsContent>

        <TabsContent value="progress">
          <div className="space-y-3">
            {notes.length === 0 && <div className="bg-white border border-slate-200 rounded-xl p-6 text-sm text-slate-500 text-center">No progress notes yet. Add via attendance tab.</div>}
            {notes.map((n) => {
              const stu = roster.find((r) => r.student_id === n.student_id);
              return (
                <div key={n.id} className="bg-white border border-slate-200 rounded-xl p-4">
                  <div className="flex justify-between text-sm">
                    <div className="font-medium text-slate-900">{stu?.student?.first_name} {stu?.student?.last_name}</div>
                    <div className="text-xs text-slate-500">{formatDate(n.created_at)}</div>
                  </div>
                  <div className="text-sm text-slate-700 mt-1">{n.note}</div>
                </div>
              );
            })}
          </div>
        </TabsContent>
      </Tabs>

      <Dialog open={lessonOpen} onOpenChange={setLessonOpen}>
        <DialogContent className="max-w-xl">
          <DialogHeader><DialogTitle className="font-display tracking-tight">New lesson plan</DialogTitle></DialogHeader>
          <div className="grid grid-cols-1 gap-3">
            <div><Label>Date</Label><Input type="date" value={lessonForm.date} onChange={(e) => setLessonForm({ ...lessonForm, date: e.target.value })} className="mt-1" /></div>
            <div><Label>Objective</Label><Input value={lessonForm.objective} onChange={(e) => setLessonForm({ ...lessonForm, objective: e.target.value })} className="mt-1" data-testid="lesson-objective" /></div>
            <div><Label>Warmup</Label><Textarea value={lessonForm.warmup} onChange={(e) => setLessonForm({ ...lessonForm, warmup: e.target.value })} className="mt-1" /></div>
            <div><Label>Skill drill</Label><Textarea value={lessonForm.skill_drill} onChange={(e) => setLessonForm({ ...lessonForm, skill_drill: e.target.value })} className="mt-1" /></div>
            <div><Label>Game activity</Label><Textarea value={lessonForm.game_activity} onChange={(e) => setLessonForm({ ...lessonForm, game_activity: e.target.value })} className="mt-1" /></div>
            <div><Label>Fitness</Label><Textarea value={lessonForm.fitness_activity} onChange={(e) => setLessonForm({ ...lessonForm, fitness_activity: e.target.value })} className="mt-1" /></div>
            <div><Label>Homework</Label><Textarea value={lessonForm.homework} onChange={(e) => setLessonForm({ ...lessonForm, homework: e.target.value })} className="mt-1" /></div>
            <div><Label>Coach notes</Label><Textarea value={lessonForm.coach_notes} onChange={(e) => setLessonForm({ ...lessonForm, coach_notes: e.target.value })} className="mt-1" /></div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setLessonOpen(false)}>Cancel</Button>
            <Button onClick={saveLesson} className="bg-blue-600 hover:bg-blue-500 text-white" data-testid="save-lesson">Save</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={!!noteOpen} onOpenChange={(v) => !v && setNoteOpen(null)}>
        <DialogContent>
          <DialogHeader><DialogTitle className="font-display tracking-tight">Add progress note</DialogTitle></DialogHeader>
          <Textarea value={noteText} onChange={(e) => setNoteText(e.target.value)} rows={5} placeholder="Footwork improving, needs work on backhand drop…" data-testid="progress-note-text" />
          <DialogFooter>
            <Button variant="outline" onClick={() => setNoteOpen(null)}>Cancel</Button>
            <Button onClick={saveNote} className="bg-blue-600 hover:bg-blue-500 text-white" data-testid="save-progress-note">Save</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
