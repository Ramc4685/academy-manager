"use client";

import { useParams, useSearchParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  getCoachSessionSkillBoard,
  recordTestAttempt,
  updateSkillStatus,
  type SkillStatus,
} from "@/lib/api/curriculum";
import { SkillBoardView, type SkillBoardActions } from "@/components/pathway/skill-board";

export default function CoachSessionProgressPage() {
  const { id: sessionId } = useParams<{ id: string }>();
  const searchParams = useSearchParams();
  const programId = searchParams.get("program_id") ?? "";
  const queryClient = useQueryClient();

  const boardKey = ["coach", "skill-board", sessionId, programId || "default"];
  const { data: board, isLoading, isError } = useQuery({
    queryKey: boardKey,
    queryFn: () => getCoachSessionSkillBoard(sessionId, programId || undefined),
    enabled: Boolean(sessionId),
  });

  const invalidate = () => void queryClient.invalidateQueries({ queryKey: boardKey });

  const statusMutation = useMutation({
    mutationFn: (args: {
      studentId: string;
      skillId: string;
      levelId: string;
      status: SkillStatus;
    }) =>
      updateSkillStatus(args.studentId, args.skillId, {
        program_id: board?.program_id ?? "",
        level_id: args.levelId,
        status: args.status,
      }),
    onSettled: invalidate,
  });

  const testMutation = useMutation({
    mutationFn: (args: {
      studentId: string;
      skillId: string;
      levelId: string;
      attempts: number;
      successes: number;
      notes: string;
    }) =>
      recordTestAttempt(args.studentId, args.skillId, {
        program_id: board?.program_id ?? "",
        level_id: args.levelId,
        attempts_count: args.attempts,
        success_count: args.successes,
        notes: args.notes || undefined,
        session_id: sessionId,
      }),
    onSettled: invalidate,
  });

  const actions: SkillBoardActions = {
    setStatus: (args) => statusMutation.mutateAsync(args),
    quickPass: (args) =>
      testMutation.mutateAsync({ ...args, attempts: 1, successes: 1, notes: "Quick pass" }),
    recordTest: (args) => testMutation.mutateAsync(args),
  };

  return (
    <section data-testid="coach-session-progress" className="space-y-4">
      <div>
        <h1 className="text-xl font-semibold">Session skill board</h1>
        <p className="text-sm text-neutral-500">{board?.program_name ?? ""}</p>
      </div>

      {isError && (
        <p role="alert" className="rounded-md bg-red-50 p-3 text-sm text-red-700">
          Could not load the skill board.
        </p>
      )}
      {isLoading ? (
        <div className="space-y-2">
          {[0, 1, 2].map((i) => (
            <div
              key={i}
              className="h-20 animate-pulse rounded-xl bg-neutral-100 dark:bg-neutral-800"
            />
          ))}
        </div>
      ) : board ? (
        <SkillBoardView board={board} actions={actions} />
      ) : null}
    </section>
  );
}
