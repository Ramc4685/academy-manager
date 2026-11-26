"use client";

/**
 * S65 "Running late": tell the coaches of today's class that a child is on
 * the way. One DM per coach on the class date (lead, cover, assistants) with
 * only the line in `runningLateMessage`. Attendance is not changed; the coach
 * marks Late on arrival.
 */

import { useState } from "react";
import { useMutation } from "@tanstack/react-query";

import { sendDm, type AdminToday, type AdminTodayClass, type AdminTodayRosterRow } from "@/lib/api/admin";
import { Button } from "@/components/ds/button";
import { Modal } from "@/components/ds/modal";
import { useToast } from "@/components/ds/toast";

import { HOW_LATE_MAX, classClock, runningLateMessage } from "./format";

type Choice = { row: AdminTodayRosterRow; cls: AdminTodayClass };

/** Children in today's classes that have not finished or been cancelled. */
export function runningLateChoices(today: AdminToday | undefined, search: string): Choice[] {
  const needle = search.trim().toLocaleLowerCase();
  return (today?.classes ?? [])
    .filter((cls) => cls.phase !== "cancelled" && cls.phase !== "finished")
    .flatMap((cls) => cls.roster.map((row) => ({ row, cls })))
    .filter(({ row }) => !needle || row.full_name.toLocaleLowerCase().includes(needle));
}

function coachLine(cls: AdminTodayClass): string {
  const lead = cls.cover_coach_name ?? cls.coach_name;
  if (cls.staff_ids.length === 0) return "No coach is assigned to this class, so there is nobody to tell.";
  const who = lead ? `Coach ${lead}` : "the coach";
  const others = cls.staff_ids.length > 1 ? " and the class's other coaches" : "";
  return `This sends a message to ${who}${others}. Attendance is not changed.`;
}

export function RunningLateDialog({ today, onClose }: { today: AdminToday | undefined; onClose: () => void }) {
  const { toast } = useToast();
  const [search, setSearch] = useState("");
  const [picked, setPicked] = useState<Choice | null>(null);
  const [howLate, setHowLate] = useState("");
  const timezone = today?.timezone ?? null;

  const send = useMutation({
    mutationFn: async ({ row, cls }: Choice) => {
      const body = runningLateMessage(row.full_name, cls, timezone, howLate);
      await Promise.all(cls.staff_ids.map((recipient_id) => sendDm({ recipient_id, body })));
    },
    onSuccess: (_data, { row, cls }) => {
      const lead = cls.cover_coach_name ?? cls.coach_name;
      toast({
        kind: "success",
        title: `${lead ? `Coach ${lead}` : "The coach"} has been told ${row.full_name} is running late.`,
      });
      onClose();
    },
  });

  const choices = runningLateChoices(today, search);

  return (
    <Modal open onClose={onClose} title="Running late" size="md">
      {picked ? (
        <div className="space-y-3" data-testid="running-late-preview">
          <p className="rounded-lg border border-rally-line bg-rally-paper p-3 text-sm text-rally-ink">
            {runningLateMessage(picked.row.full_name, picked.cls, timezone, howLate)}
          </p>
          <label className="block text-xs font-semibold text-rally-muted">
            How late? (optional)
            <input
              value={howLate}
              maxLength={HOW_LATE_MAX}
              onChange={(e) => setHowLate(e.target.value)}
              placeholder="About 10 minutes"
              className="mt-1 min-h-touch w-full rounded-lg border border-rally-line px-3 text-sm"
              data-testid="running-late-how-late"
            />
          </label>
          <p className="text-sm text-rally-muted">{coachLine(picked.cls)}</p>
          {send.isError ? (
            <p role="alert" className="text-sm text-status-red-800">
              The message was not sent. Try again.
            </p>
          ) : null}
          <div className="flex justify-end gap-2">
            <Button variant="secondary" size="sm" onClick={() => setPicked(null)} disabled={send.isPending}>
              Back
            </Button>
            <Button
              size="sm"
              onClick={() => send.mutate(picked)}
              disabled={send.isPending || picked.cls.staff_ids.length === 0}
              data-testid="running-late-send"
            >
              {send.isPending ? "Sending…" : "Tell the coach"}
            </Button>
          </div>
        </div>
      ) : (
        <div className="space-y-3">
          <label className="block text-xs font-semibold text-rally-muted">
            Child
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search today's classes"
              autoComplete="off"
              className="mt-1 min-h-touch w-full rounded-lg border border-rally-line px-3 text-sm"
              data-testid="running-late-search"
            />
          </label>
          {choices.length === 0 ? (
            <p className="text-sm text-rally-subtle">
              {today ? "No child in today's remaining classes matches." : "Loading today's classes…"}
            </p>
          ) : (
            <ul role="list" className="max-h-[50vh] divide-y divide-rally-line overflow-y-auto">
              {choices.map((choice) => (
                <li key={`${choice.cls.occurrence_id}-${choice.row.student_id}`}>
                  <button
                    type="button"
                    onClick={() => setPicked(choice)}
                    className="flex min-h-touch w-full flex-col items-start justify-center px-1 py-2 text-left hover:bg-rally-paper"
                  >
                    <span className="text-sm font-semibold text-rally-ink">{choice.row.full_name}</span>
                    <span className="text-[13px] text-rally-muted">
                      {choice.cls.title} · {classClock(choice.cls.start_at, timezone)}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </Modal>
  );
}
