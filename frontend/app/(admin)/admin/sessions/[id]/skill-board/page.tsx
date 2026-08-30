"use client";

import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft } from "lucide-react";

import {
  getAdminSessionSkillBoard,
  recordAdminTestAttempt,
  updateAdminSkillStatus,
  type SkillStatus,
} from "@/lib/api/curriculum";
import { SkillBoardView, type SkillBoardActions } from "@/components/pathway/skill-board";
import {
  buildSessionSkillBoardHref,
  buildStudentProgressHref,
} from "@/lib/navigation/admin-student-progress-return";

export default function AdminSessionSkillBoardPage() {
  const { id: sessionId } = useParams<{ id: string }>();
  const searchParams = useSearchParams();
  const programId = searchParams.get("program_id") ?? "";
  const queryClient = useQueryClient();

  const boardKey = ["admin", "skill-board", sessionId, programId || "default"];
  const { data: board, isLoading, isError } = useQuery({
    queryKey: boardKey,
    queryFn: () => getAdminSessionSkillBoard(sessionId, programId || undefined),
    enabled: Boolean(sessionId),
  });

  const invalidate = () => void queryClient.invalidateQueries({ queryKey: boardKey });

  const statusMutation = useMutation({
    mutationFn: (args: {
      studentId: string;
      skillId: string;
      levelId: string;
      status: SkillStatus;
    }) => {
      if (!board?.program_id) return Promise.reject(new Error("Board not loaded"));
      return updateAdminSkillStatus(args.studentId, args.skillId, {
        program_id: board.program_id,
        level_id: args.levelId,
        status: args.status,
      });
    },
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
    }) => {
      if (!board?.program_id) return Promise.reject(new Error("Board not loaded"));
      return recordAdminTestAttempt(args.studentId, args.skillId, {
        program_id: board.program_id,
        level_id: args.levelId,
        attempts_count: args.attempts,
        success_count: args.successes,
        notes: args.notes || undefined,
        session_id: sessionId,
      });
    },
    onSettled: invalidate,
  });

  const actions: SkillBoardActions = {
    setStatus: (args) => statusMutation.mutateAsync(args),
    quickPass: (args) =>
      testMutation.mutateAsync({ ...args, attempts: 1, successes: 1, notes: "Quick pass" }),
    recordTest: (args) => testMutation.mutateAsync(args),
  };

  // Carry the program the board actually rendered (not just the URL param, which
  // is empty when the board resolved a default) into both the placement screen
  // and the link back, so placing a student resolves them on this same board.
  const boardProgramId = board?.program_id || programId;
  const boardHref = buildSessionSkillBoardHref({
    sessionId,
    programId: boardProgramId,
  });

  return (
    <section data-testid="admin-session-skill-board" className="space-y-4">
      <Link
        href={`/admin/sessions/${sessionId}` as Parameters<typeof Link>[0]["href"]}
        className="inline-flex items-center gap-1.5 text-sm text-rally-muted hover:text-rally-ink"
      >
        <ArrowLeft className="size-4" aria-hidden="true" />
        <span>Back to session</span>
      </Link>
      <div>
        <h1 className="text-2xl font-semibold">Skill board</h1>
        <p className="text-sm text-neutral-500">{board?.program_name ?? ""}</p>
      </div>

      {isError && (
        <p role="alert" className="rounded-md bg-red-50 p-3 text-sm text-red-700">
          Could not load the skill board.
        </p>
      )}
      {isLoading ? (
        <div className="h-40 animate-pulse rounded-xl bg-neutral-100 dark:bg-neutral-800" />
      ) : board ? (
        <SkillBoardView
          board={board}
          actions={actions}
          renderUnplacedAction={(student) => (
            <Link
              href={
                buildStudentProgressHref({
                  studentId: student.student_id,
                  programId: boardProgramId,
                  returnTo: boardHref,
                  returnLabel: "Back to skill board",
                }) as Parameters<typeof Link>[0]["href"]
              }
              className="rounded-md border border-neutral-300 px-3 py-1.5 text-xs font-medium hover:bg-neutral-50"
            >
              Place in level
            </Link>
          )}
        />
      ) : null}
    </section>
  );
}
