"use client";

import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";

import { getFullPathway, placeStudentsInBulk } from "@/lib/api/curriculum";
import { summarizePlacement } from "@/lib/admin/bulk-placement";
import { Button } from "@/components/ds/button";
import { Modal } from "@/components/ds/modal";

/**
 * Place the selected students on one level and credit skills they already
 * have. Credits never queue a level-up, and stay out of tonight's parent
 * email unless the owner turns the email on.
 */
export function BulkPlacementModal({
  open,
  programId,
  studentIds,
  onClose,
  onPlaced,
}: {
  open: boolean;
  programId: string;
  studentIds: string[];
  onClose: () => void;
  onPlaced: () => void;
}) {
  const [levelId, setLevelId] = useState("");
  const [credited, setCredited] = useState<string[]>([]);
  const [notifyParents, setNotifyParents] = useState(false);
  const [reason, setReason] = useState("");

  const pathway = useQuery({
    queryKey: ["admin", "pathway", programId],
    queryFn: () => getFullPathway(programId),
    enabled: open && Boolean(programId),
  });
  const levels = (pathway.data?.levels ?? []).filter((l) => l.level.is_active);
  const level = levels.find((l) => l.level.level_id === levelId);

  const place = useMutation({
    mutationFn: () =>
      placeStudentsInBulk({
        program_id: programId,
        level_id: levelId,
        student_ids: studentIds,
        credited_skill_ids: credited,
        notify_parents: notifyParents,
        reason: reason.trim() || undefined,
      }),
    onSuccess: () => onPlaced(),
  });

  const pickLevel = (next: string) => {
    setLevelId(next);
    setCredited([]);
  };
  const toggle = (skillId: string) =>
    setCredited((prev) =>
      prev.includes(skillId) ? prev.filter((id) => id !== skillId) : [...prev, skillId],
    );

  return (
    <Modal
      open={open}
      onClose={onClose}
      size="lg"
      title={`Place ${studentIds.length} student${studentIds.length === 1 ? "" : "s"}`}
      footer={
        <div className="flex justify-end gap-2">
          <Button variant="secondary" size="sm" onClick={onClose}>
            {place.isSuccess ? "Done" : "Cancel"}
          </Button>
          {!place.isSuccess && (
            <Button
              size="sm"
              disabled={!levelId || place.isPending}
              onClick={() => place.mutate()}
            >
              {place.isPending ? "Placing..." : "Place"}
            </Button>
          )}
        </div>
      }
    >
      <div data-testid="bulk-placement" className="space-y-4 text-sm">
        <label className="block">
          <span className="mb-1 block text-xs font-medium text-neutral-600">Level</span>
          <select
            value={levelId}
            onChange={(e) => pickLevel(e.target.value)}
            disabled={pathway.isLoading || place.isPending}
            className="w-full rounded-md border border-neutral-300 bg-white px-3 py-2 text-sm"
          >
            <option value="">Choose a level</option>
            {levels.map((l) => (
              <option key={l.level.level_id} value={l.level.level_id}>
                Level {l.level.sequence} · {l.level.name}
              </option>
            ))}
          </select>
        </label>

        {level && level.skills.length > 0 && (
          <fieldset className="space-y-1.5">
            <legend className="mb-1 text-xs font-medium text-neutral-600">
              Skills they already have (marked passed, no test)
            </legend>
            {level.skills.map(({ skill }) => (
              <label key={skill.skill_id} className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={credited.includes(skill.skill_id)}
                  onChange={() => toggle(skill.skill_id)}
                  disabled={place.isPending}
                />
                {skill.name}
              </label>
            ))}
          </fieldset>
        )}

        <label className="flex items-center gap-2">
          <input
            type="checkbox"
            checked={notifyParents}
            onChange={(e) => setNotifyParents(e.target.checked)}
            disabled={place.isPending}
          />
          Include credited skills in tonight&apos;s parent email
        </label>

        <label className="block">
          <span className="mb-1 block text-xs font-medium text-neutral-600">
            Reason (optional, kept in the audit log)
          </span>
          <input
            value={reason}
            maxLength={500}
            onChange={(e) => setReason(e.target.value)}
            disabled={place.isPending}
            className="w-full rounded-md border border-neutral-300 px-3 py-2 text-sm"
          />
        </label>

        <p className="text-xs text-neutral-500">
          Skills a student already earned are kept. A level-up waiting for approval is withdrawn.
        </p>
        {place.isSuccess && (
          <p role="status" className="rounded-md bg-green-50 p-2 text-green-800">
            {summarizePlacement(place.data.results)}
          </p>
        )}
        {place.isError && (
          <p role="alert" className="rounded-md bg-red-50 p-2 text-red-700">
            Couldn&apos;t finish placing. Some students may have moved; check the table before trying again.
          </p>
        )}
        {pathway.isError && (
          <p role="alert" className="rounded-md bg-red-50 p-2 text-red-700">
            Couldn&apos;t load this program&apos;s levels.
          </p>
        )}
      </div>
    </Modal>
  );
}
