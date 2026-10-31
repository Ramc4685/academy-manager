"use client";

import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { Button, Card, Chip, Overline, Skeleton } from "@/components/ds";
import { ErrorNotice } from "@/components/ds/error-notice";
import { listAdminUsers } from "@/lib/api/admin";
import {
  addFamilyFollowUp,
  addFamilyNote,
  deleteFamilyNote,
  editFamilyNote,
  fetchFamilyFollowUps,
  fetchFamilyNotes,
  updateFamilyFollowUp,
  type FamilyNote,
  type FollowUp,
} from "@/lib/api/admin-family-crm";
import { getCurrentUser } from "@/lib/api/me";
import { formatInstantDay } from "@/lib/money";
import { queryKeys } from "@/lib/query/keys";

import {
  MAX_FOLLOW_UP_TITLE_LEN,
  MAX_NOTE_BODY_LEN,
  bucketLabel,
  bucketVariant,
  dueLabel,
  followUpDraftError,
  noteDraftError,
  sortFollowUps,
  staffName,
  staffOptions,
  type StaffOption,
} from "./family-notes";

const inputClass =
  "w-full rounded-lg border border-rally-line bg-white px-3 py-2 text-sm text-rally-ink focus:outline-none focus:ring-2 focus:ring-rally-cobalt-600/30";

function errorText(error: unknown): string {
  return (error as Error | null)?.message || "Something went wrong. Try again.";
}

/**
 * Notes & follow-ups (People CRM spec §5, Phase 4a): the team's own notes on
 * this family and its dated follow-ups. Coach notes are not here; they stay
 * read-only in the child drawer and are never edited from the CRM.
 */
export function NotesTab({ parentId }: { parentId: string }) {
  const staffQuery = useQuery({
    queryKey: queryKeys.admin.users("crm-staff"),
    queryFn: () => listAdminUsers(undefined, { roles: ["admin", "owner"] }),
    staleTime: 5 * 60_000,
  });
  const meQuery = useQuery({
    queryKey: queryKeys.admin.currentUser(),
    queryFn: getCurrentUser,
    staleTime: 5 * 60_000,
  });
  const staff = staffOptions(staffQuery.data?.users ?? []);
  const meId = meQuery.data?.user_id ?? null;

  return (
    <div className="grid gap-4 lg:grid-cols-2" data-testid="family-notes-tab">
      <FollowUpsSection parentId={parentId} staff={staff} meId={meId} />
      <NotesSection parentId={parentId} staff={staff} meId={meId} />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Notes
// ---------------------------------------------------------------------------

function NotesSection({
  parentId,
  staff,
  meId,
}: {
  parentId: string;
  staff: StaffOption[];
  meId: string | null;
}) {
  const qc = useQueryClient();
  const key = queryKeys.admin.familyNotes(parentId);
  const notes = useQuery({ queryKey: key, queryFn: () => fetchFamilyNotes(parentId) });
  const [draft, setDraft] = useState("");
  const [draftError, setDraftError] = useState<string | null>(null);

  const add = useMutation({
    mutationFn: (body: string) => addFamilyNote(parentId, body),
    onSuccess: () => {
      setDraft("");
      void qc.invalidateQueries({ queryKey: key });
    },
  });

  const submit = (event: FormEvent) => {
    event.preventDefault();
    const problem = noteDraftError(draft);
    setDraftError(problem);
    if (!problem && !add.isPending) add.mutate(draft);
  };

  const list = notes.data?.notes ?? [];

  return (
    <Card p={20} data-testid="family-notes">
      <Overline>Notes</Overline>
      <form className="mt-2 space-y-2" onSubmit={submit} noValidate>
        <label htmlFor="family-note-draft" className="sr-only">
          New note
        </label>
        <textarea
          id="family-note-draft"
          data-testid="family-note-draft"
          className={`${inputClass} min-h-20`}
          placeholder="Add a note for the team"
          maxLength={MAX_NOTE_BODY_LEN}
          value={draft}
          aria-invalid={draftError ? true : undefined}
          aria-describedby={draftError ? "family-note-draft-error" : undefined}
          onChange={(e) => setDraft(e.target.value)}
        />
        {(draftError || add.isError) && (
          <p
            id="family-note-draft-error"
            role="alert"
            className="text-xs text-status-red-700"
            data-testid="family-note-error"
          >
            {draftError ?? errorText(add.error)}
          </p>
        )}
        <div className="flex justify-end">
          <Button type="submit" size="sm" disabled={add.isPending} data-testid="family-note-add">
            {add.isPending ? "Saving…" : "Add note"}
          </Button>
        </div>
      </form>

      {notes.isLoading ? (
        <div className="mt-3">
          <Skeleton lines={3} />
        </div>
      ) : notes.isError ? (
        <ErrorNotice
          className="mt-3"
          testId="family-notes-error"
          message="Could not load the notes."
          onRetry={() => void notes.refetch()}
          retrying={notes.isFetching}
        />
      ) : list.length === 0 ? (
        <p className="mt-3 text-sm text-rally-muted" data-testid="family-notes-empty">
          No notes yet.
        </p>
      ) : (
        <ul className="mt-3 divide-y divide-rally-line" data-testid="family-notes-list">
          {list.map((note) => (
            <NoteRow
              key={note.note_id}
              parentId={parentId}
              note={note}
              author={staffName(staff, note.author_user_id, meId)}
            />
          ))}
        </ul>
      )}
    </Card>
  );
}

function NoteRow({
  parentId,
  note,
  author,
}: {
  parentId: string;
  note: FamilyNote;
  author: string;
}) {
  const qc = useQueryClient();
  const key = queryKeys.admin.familyNotes(parentId);
  const [editing, setEditing] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [body, setBody] = useState(note.body);
  const [problem, setProblem] = useState<string | null>(null);

  const edit = useMutation({
    mutationFn: (text: string) => editFamilyNote(parentId, note.note_id, text),
    onSuccess: () => {
      setEditing(false);
      void qc.invalidateQueries({ queryKey: key });
    },
  });
  const remove = useMutation({
    mutationFn: () => deleteFamilyNote(parentId, note.note_id),
    onSuccess: () => void qc.invalidateQueries({ queryKey: key }),
  });

  const save = (event: FormEvent) => {
    event.preventDefault();
    const err = noteDraftError(body);
    setProblem(err);
    if (!err && !edit.isPending) edit.mutate(body);
  };

  const failure =
    problem ??
    (edit.isError ? errorText(edit.error) : null) ??
    (remove.isError ? errorText(remove.error) : null);

  return (
    <li className="py-3" data-testid={`family-note-${note.note_id}`}>
      <p className="text-xs text-rally-muted">
        {author} · {formatInstantDay(note.created_at)}
        {note.edited ? " · edited" : ""}
      </p>
      {editing ? (
        <form className="mt-1 space-y-2" onSubmit={save} noValidate>
          <label htmlFor={`note-edit-${note.note_id}`} className="sr-only">
            Edit note
          </label>
          <textarea
            id={`note-edit-${note.note_id}`}
            data-testid="family-note-edit-body"
            className={`${inputClass} min-h-20`}
            maxLength={MAX_NOTE_BODY_LEN}
            value={body}
            onChange={(e) => setBody(e.target.value)}
          />
          <div className="flex justify-end gap-2">
            <Button
              size="sm"
              variant="secondary"
              onClick={() => {
                setEditing(false);
                setBody(note.body);
                setProblem(null);
              }}
            >
              Cancel
            </Button>
            <Button
              type="submit"
              size="sm"
              disabled={edit.isPending}
              data-testid="family-note-save"
            >
              {edit.isPending ? "Saving…" : "Save"}
            </Button>
          </div>
        </form>
      ) : (
        <p className="mt-1 whitespace-pre-wrap break-words text-sm text-rally-ink">{note.body}</p>
      )}
      {failure && (
        <p role="alert" className="mt-1 text-xs text-status-red-700">
          {failure}
        </p>
      )}
      {note.can_edit && !editing && (
        <div className="mt-2 flex flex-wrap items-center gap-2">
          {confirming ? (
            <>
              <span className="text-xs text-rally-ink">Delete this note?</span>
              <Button
                size="sm"
                variant="danger"
                disabled={remove.isPending}
                data-testid="family-note-delete-confirm"
                onClick={() => remove.mutate()}
              >
                {remove.isPending ? "Deleting…" : "Delete"}
              </Button>
              <Button size="sm" variant="secondary" onClick={() => setConfirming(false)}>
                Keep
              </Button>
            </>
          ) : (
            <>
              <Button
                size="sm"
                variant="secondary"
                data-testid="family-note-edit"
                onClick={() => {
                  setBody(note.body);
                  setEditing(true);
                }}
              >
                Edit
              </Button>
              <Button
                size="sm"
                variant="ghost"
                data-testid="family-note-delete"
                onClick={() => setConfirming(true)}
              >
                Delete
              </Button>
            </>
          )}
        </div>
      )}
    </li>
  );
}

// ---------------------------------------------------------------------------
// Follow-ups
// ---------------------------------------------------------------------------

function FollowUpsSection({
  parentId,
  staff,
  meId,
}: {
  parentId: string;
  staff: StaffOption[];
  meId: string | null;
}) {
  const qc = useQueryClient();
  const key = queryKeys.admin.familyFollowUps(parentId);
  const followUps = useQuery({ queryKey: key, queryFn: () => fetchFamilyFollowUps(parentId) });
  const [title, setTitle] = useState("");
  const [dueOn, setDueOn] = useState("");
  const [assignee, setAssignee] = useState("");
  const [problem, setProblem] = useState<string | null>(null);

  // Default the assignee to the signed-in staff member, the date to today.
  const assigneeValue = assignee || (meId && staff.some((s) => s.userId === meId) ? meId : "");
  const dueValue = dueOn || followUps.data?.today || "";

  const refresh = () => {
    void qc.invalidateQueries({ queryKey: key });
    void qc.invalidateQueries({ queryKey: queryKeys.admin.followUpQueueAll() });
  };

  const add = useMutation({
    mutationFn: () =>
      addFamilyFollowUp(parentId, {
        title: title.trim(),
        due_on: dueValue,
        assignee_user_id: assigneeValue,
      }),
    onSuccess: () => {
      setTitle("");
      setDueOn("");
      refresh();
    },
  });

  const submit = (event: FormEvent) => {
    event.preventDefault();
    const err = followUpDraftError({ title, dueOn: dueValue, assigneeUserId: assigneeValue });
    setProblem(err);
    if (!err && !add.isPending) add.mutate();
  };

  const rows = sortFollowUps(followUps.data?.follow_ups ?? []);

  return (
    <Card p={20} data-testid="family-follow-ups">
      <Overline>Follow-ups</Overline>
      <form className="mt-2 grid gap-2 sm:grid-cols-2" onSubmit={submit} noValidate>
        <div className="sm:col-span-2">
          <label
            htmlFor="follow-up-title"
            className="block text-xs font-semibold text-rally-muted"
          >
            What needs doing
          </label>
          <input
            id="follow-up-title"
            data-testid="follow-up-title"
            className={inputClass}
            maxLength={MAX_FOLLOW_UP_TITLE_LEN}
            placeholder="Call back about the trial"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
          />
        </div>
        <div>
          <label htmlFor="follow-up-due" className="block text-xs font-semibold text-rally-muted">
            Due
          </label>
          <input
            id="follow-up-due"
            data-testid="follow-up-due"
            type="date"
            className={inputClass}
            value={dueValue}
            onChange={(e) => setDueOn(e.target.value)}
          />
        </div>
        <div>
          <label
            htmlFor="follow-up-assignee"
            className="block text-xs font-semibold text-rally-muted"
          >
            For
          </label>
          <select
            id="follow-up-assignee"
            data-testid="follow-up-assignee"
            className={inputClass}
            value={assigneeValue}
            onChange={(e) => setAssignee(e.target.value)}
          >
            <option value="">Pick a staff member</option>
            {staff.map((s) => (
              <option key={s.userId} value={s.userId}>
                {s.userId === meId ? `${s.label} (you)` : s.label}
              </option>
            ))}
          </select>
        </div>
        {(problem || add.isError) && (
          <p
            role="alert"
            className="text-xs text-status-red-700 sm:col-span-2"
            data-testid="follow-up-error"
          >
            {problem ?? errorText(add.error)}
          </p>
        )}
        <div className="flex justify-end sm:col-span-2">
          <Button type="submit" size="sm" disabled={add.isPending} data-testid="follow-up-add">
            {add.isPending ? "Saving…" : "Add follow-up"}
          </Button>
        </div>
      </form>

      {followUps.isLoading ? (
        <div className="mt-3">
          <Skeleton lines={3} />
        </div>
      ) : followUps.isError ? (
        <ErrorNotice
          className="mt-3"
          testId="family-follow-ups-error"
          message="Could not load the follow-ups."
          onRetry={() => void followUps.refetch()}
          retrying={followUps.isFetching}
        />
      ) : rows.length === 0 ? (
        <p className="mt-3 text-sm text-rally-muted" data-testid="family-follow-ups-empty">
          No follow-ups yet.
        </p>
      ) : (
        <ul className="mt-3 divide-y divide-rally-line" data-testid="family-follow-ups-list">
          {rows.map((row) => (
            <FollowUpRow
              key={row.follow_up_id}
              parentId={parentId}
              row={row}
              assignee={staffName(staff, row.assignee_user_id, meId)}
              onChanged={refresh}
            />
          ))}
        </ul>
      )}
    </Card>
  );
}

function FollowUpRow({
  parentId,
  row,
  assignee,
  onChanged,
}: {
  parentId: string;
  row: FollowUp;
  assignee: string;
  onChanged: () => void;
}) {
  const toggle = useMutation({
    mutationFn: () =>
      updateFamilyFollowUp(parentId, row.follow_up_id, {
        status: row.status === "open" ? "done" : "open",
      }),
    onSuccess: onChanged,
  });
  const done = row.status === "done";
  return (
    <li
      className="flex flex-wrap items-center justify-between gap-3 py-3"
      data-testid={`follow-up-${row.follow_up_id}`}
      data-status={row.status}
    >
      <div className="min-w-0">
        <p
          className={`text-sm font-medium ${done ? "text-rally-muted line-through" : "text-rally-ink"}`}
        >
          {row.title}
        </p>
        <p className="mt-0.5 flex flex-wrap items-center gap-2 text-xs text-rally-muted">
          <Chip variant={bucketVariant(row.bucket)} label={bucketLabel(row.bucket)} />
          <span>Due {dueLabel(row.due_on)}</span>
          <span>· {assignee}</span>
        </p>
        {toggle.isError && (
          <p role="alert" className="mt-1 text-xs text-status-red-700">
            {errorText(toggle.error)}
          </p>
        )}
      </div>
      <Button
        size="sm"
        variant={done ? "ghost" : "secondary"}
        disabled={toggle.isPending}
        data-testid={done ? "follow-up-reopen" : "follow-up-done"}
        onClick={() => toggle.mutate()}
      >
        {done ? "Reopen" : "Mark done"}
      </Button>
    </li>
  );
}
