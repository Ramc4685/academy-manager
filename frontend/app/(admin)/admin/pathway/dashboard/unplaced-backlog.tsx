"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { listUnplacedStudents, placeUnplacedBacklog } from "@/lib/api/curriculum";
import { queryKeys } from "@/lib/query/keys";
import { useIsOwner } from "@/components/admin/owner-context";
import { Button } from "@/components/ds/button";
import { Card } from "@/components/ds/card";
import { ConfirmActionDialog } from "@/components/ds/confirm-action-dialog";

/**
 * D-10 backlog: the owner sees exactly which active students have no level,
 * then places them all on the first level. Nothing is placed without the list.
 */
export function UnplacedBacklog({ firstLevelName }: { firstLevelName: string }) {
  const isOwner = useIsOwner();
  const queryClient = useQueryClient();
  const [confirming, setConfirming] = useState(false);
  const query = useQuery({
    queryKey: queryKeys.admin.pathwayUnplaced(),
    queryFn: listUnplacedStudents,
  });
  const students = query.data?.students ?? [];
  const place = useMutation({
    mutationFn: () => placeUnplacedBacklog(students.map((s) => s.student_id)),
    meta: { success: "Students placed on the first level" },
    onSuccess: () => {
      setConfirming(false);
      void queryClient.invalidateQueries({ queryKey: ["admin", "pathway"] });
    },
  });
  if (students.length === 0) return null;

  return (
    <Card p={20} data-testid="pathway-unplaced-backlog">
      <h2 className="font-display text-lg font-bold text-rally-ink">Not on a level yet</h2>
      <p className="mt-1 text-sm text-rally-muted">
        Coaches cannot record a skill for these {students.length} active students until they have a
        level. New enrollments now start on {firstLevelName} by themselves.
      </p>
      <ul className="mt-3 flex flex-wrap gap-2 text-sm" data-testid="pathway-unplaced-list">
        {students.map((s) => (
          <li key={s.student_id} className="rounded-full bg-status-slate-100 px-3 py-1">
            {s.student_name}
          </li>
        ))}
      </ul>
      {isOwner ? (
        <Button className="mt-4" size="sm" onClick={() => setConfirming(true)} data-testid="pathway-place-backlog">
          Place all on {firstLevelName}
        </Button>
      ) : (
        <p className="mt-3 text-xs text-rally-muted">The academy owner can place them all at once.</p>
      )}
      <ConfirmActionDialog
        open={confirming}
        onOpenChange={setConfirming}
        overline="Skill pathway"
        title={`Place ${students.length} students on ${firstLevelName}?`}
        subject={students.map((s) => s.student_name).join(", ")}
        consequence={
          <p>
            Each starts {firstLevelName} with no skills passed. Anyone placed since this list loaded
            keeps their level. You can move a child later from their progress page.
          </p>
        }
        confirmLabel="Place them"
        confirmVariant="primary"
        pending={place.isPending}
        error={place.error?.message}
        onConfirm={() => place.mutate()}
      />
    </Card>
  );
}
