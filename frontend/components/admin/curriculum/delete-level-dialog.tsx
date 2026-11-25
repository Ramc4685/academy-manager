"use client";

import { useMutation } from "@tanstack/react-query";

import { deleteLevel, type PathwayLevel } from "@/lib/api/curriculum";
import type { ApiError } from "@/lib/api/client";
import { Button } from "@/components/ds/button";
import { Modal } from "@/components/ds/modal";

/**
 * Confirms deleting a level with its skills and criteria. The editor only
 * opens it for the program's last level when the backend reports it unused
 * (removing a middle level would break level-up); a 409 (something started
 * using the level meanwhile) shows the backend's reason instead.
 */
export function DeleteLevelDialog({
  pathwayLevel,
  open,
  onClose,
  onDeleted,
}: {
  pathwayLevel: PathwayLevel;
  open: boolean;
  onClose: () => void;
  onDeleted: () => void;
}) {
  const { level, skills } = pathwayLevel;
  const criteriaCount = skills.reduce((n, s) => n + s.criteria.length, 0);

  const remove = useMutation({
    mutationFn: () => deleteLevel(level.level_id),
    onSuccess: () => {
      onDeleted();
      onClose();
    },
    // A refusal means the usage the editor holds is stale; refetch so the button goes away.
    onError: () => onDeleted(),
  });
  const error = remove.error as ApiError | null;

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={`Delete level ${level.sequence}: ${level.name}?`}
      size="sm"
      footer={
        <>
          <Button variant="secondary" size="sm" onClick={onClose} disabled={remove.isPending}>
            Cancel
          </Button>
          <Button
            variant="danger"
            size="sm"
            data-testid="confirm-delete-level"
            disabled={remove.isPending}
            onClick={() => remove.mutate()}
          >
            {remove.isPending ? "Deleting..." : "Delete level"}
          </Button>
        </>
      }
    >
      <p className="text-sm text-rally-ink">
        This removes the level, its {skills.length} skill{skills.length === 1 ? "" : "s"} and{" "}
        {criteriaCount} criteri{criteriaCount === 1 ? "on" : "a"}. No student has progress on it.
        This cannot be undone.
      </p>
      {error && (
        <p role="alert" className="text-xs text-red-600">
          {error.status === 409 ? error.message : "Could not delete the level. Try again."}
        </p>
      )}
    </Modal>
  );
}
