"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  createProgram,
  listPrograms,
  seedBadmintonPathway,
  type Program,
} from "@/lib/api/curriculum";
import { getAdminAcademy } from "@/lib/api/admin";
import { getActiveAcademyId, type ApiError } from "@/lib/api/client";
import { Card } from "@/components/ds/card";
import { Button } from "@/components/ds/button";
import { ConfirmActionDialog } from "@/components/admin/confirm-action-dialog";
import { queryKeys } from "@/lib/query/keys";
import { isBadmintonSport, titleCase } from "@/lib/pathway-sport";

const progressOverviewEnabled = process.env.NEXT_PUBLIC_SKILL_PROGRESS_OVERVIEW === "1";

/**
 * Program list, create-program form and "Seed badminton pathway" (moved from
 * the old Pathway page into Settings -> Curriculum, Settings overhaul
 * Phase 3 PR 11). `onOpenProgram` opens the editor inside the tab.
 */
export function ProgramList({ onOpenProgram }: { onOpenProgram: (programId: string) => void }) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const academyId = getActiveAcademyId() ?? "";

  const { data: programs, isLoading, isError } = useQuery({
    queryKey: ["admin", "programs", academyId],
    queryFn: () => listPrograms(academyId),
    enabled: Boolean(academyId),
  });

  const { data: academy } = useQuery({
    queryKey: queryKeys.admin.academy(),
    queryFn: () => getAdminAcademy(),
    enabled: Boolean(academyId),
  });
  const sport = academy?.sport ?? "badminton";
  const isBadminton = isBadmintonSport(sport);

  const [showForm, setShowForm] = useState(false);
  const [formName, setFormName] = useState("");
  const [formSport, setFormSport] = useState("");
  const [formDescription, setFormDescription] = useState("");
  const [seedConfirmOpen, setSeedConfirmOpen] = useState(false);

  const createMutation = useMutation({
    mutationFn: () =>
      createProgram({ name: formName, sport: formSport, description: formDescription }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["admin", "programs"] });
      setShowForm(false);
      setFormName("");
      setFormSport("");
      setFormDescription("");
    },
  });

  const seedMutation = useMutation({
    mutationFn: () => seedBadmintonPathway(),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["admin", "programs"] });
    },
  });

  const list = programs ?? [];
  // Coach, digest and student screens support one active program per
  // academy, and the backend refuses a second one (#968).
  const hasActiveProgram = list.some((p) => p.is_active);
  const createRefused = (createMutation.error as ApiError | null)?.status === 409;

  return (
    <section data-testid="admin-curriculum-programs" className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold">Programs and levels</h2>
          <p className="mt-0.5 text-sm text-neutral-500">
            Programs and their learning levels
          </p>
        </div>
        <div className="flex gap-2">
          {progressOverviewEnabled && (
            <Button
              variant="secondary"
              size="sm"
              onClick={() => router.push("/admin/pathway/progress" as any)}
            >
              Progress Overview
            </Button>
          )}
          {!hasActiveProgram && (
            <Button
              variant="primary"
              size="sm"
              onClick={() => setShowForm((v) => !v)}
            >
              {showForm ? "Cancel" : "Create Program"}
            </Button>
          )}
        </div>
      </div>

      {hasActiveProgram && (
        <p data-testid="pathway-single-program-note" className="text-sm text-neutral-500">
          Each academy has one active skill program for now. Add levels and skills to it
          instead of creating another.
        </p>
      )}

      {showForm && (
        <Card p={20}>
          <h2 className="mb-4 text-sm font-semibold">New Program</h2>
          <div className="space-y-3">
            <div>
              <label className="mb-1 block text-xs font-medium text-neutral-600">
                Name
              </label>
              <input
                type="text"
                value={formName}
                onChange={(e) => setFormName(e.target.value)}
                placeholder={`e.g. Junior ${titleCase(sport)}`}
                className="w-full rounded-md border border-neutral-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
              />
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-neutral-600">
                Sport
              </label>
              <input
                type="text"
                value={formSport}
                onChange={(e) => setFormSport(e.target.value)}
                placeholder="e.g. Badminton"
                className="w-full rounded-md border border-neutral-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
              />
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-neutral-600">
                Description
              </label>
              <textarea
                value={formDescription}
                onChange={(e) => setFormDescription(e.target.value)}
                rows={2}
                placeholder="Optional description"
                className="w-full rounded-md border border-neutral-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
              />
            </div>
            {createMutation.isError && (
              <p className="text-xs text-red-600">
                {createRefused
                  ? "This academy already has an active skill program."
                  : "Failed to create program. Please try again."}
              </p>
            )}
            <div className="flex justify-end gap-2">
              <Button variant="secondary" size="sm" onClick={() => setShowForm(false)}>
                Cancel
              </Button>
              <Button
                variant="primary"
                size="sm"
                disabled={!formName.trim() || !formSport.trim() || createMutation.isPending}
                onClick={() => createMutation.mutate()}
              >
                {createMutation.isPending ? "Creating..." : "Create"}
              </Button>
            </div>
          </div>
        </Card>
      )}

      {isError && (
        <p role="alert" className="rounded-md bg-red-50 p-3 text-sm text-red-700">
          Could not load programs.
        </p>
      )}

      {isLoading ? (
        <Skeleton />
      ) : list.length === 0 ? (
        <Card p={20}>
          <h2 className="text-sm font-semibold">Seed content</h2>
          <p className="mt-1 text-sm text-neutral-500">
            {isBadminton
              ? "No programs yet. Seed the academy's badminton skill pathway to get started, or create a custom program above. Seeding is idempotent — safe to click more than once."
              : "No programs yet. Create a custom program above to get started."}
          </p>
          {seedMutation.isError && (
            <p className="mt-2 text-xs text-red-600">Failed to seed the badminton pathway.</p>
          )}
          {isBadminton && (
            <div className="mt-3">
              <Button
                variant="primary"
                size="sm"
                disabled={seedMutation.isPending}
                onClick={() => setSeedConfirmOpen(true)}
              >
                {seedMutation.isPending ? "Seeding..." : "Seed badminton pathway"}
              </Button>
            </div>
          )}
          <ConfirmActionDialog
            open={seedConfirmOpen}
            onOpenChange={setSeedConfirmOpen}
            overline="Seed curriculum"
            title="Seed the badminton skill pathway?"
            subject="Badminton pathway — levels, skills and reference metadata"
            consequence={
              <>
                <p>
                  Creates the full curriculum for this academy. Coaches see the new levels and
                  skills immediately; no student is placed or moved, and nobody is emailed.
                </p>
                <p>Seeding is idempotent — running it again adds nothing new.</p>
              </>
            }
            confirmLabel="Seed pathway"
            confirmVariant="primary"
            pending={seedMutation.isPending}
            onConfirm={() => {
              seedMutation.mutate();
              setSeedConfirmOpen(false);
            }}
          />
        </Card>
      ) : (
        <div className="space-y-3">
          {list.map((program) => (
            <ProgramCard
              key={program.program_id}
              program={program}
              onViewPathway={() => onOpenProgram(program.program_id)}
            />
          ))}
        </div>
      )}
    </section>
  );
}

function ProgramCard({
  program,
  onViewPathway,
}: {
  program: Program;
  onViewPathway: () => void;
}) {
  return (
    <Card p={20}>
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <p className="font-semibold text-rally-base">{program.name}</p>
            {!program.is_active && (
              <span className="rounded-full bg-neutral-100 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider text-neutral-500">
                Inactive
              </span>
            )}
          </div>
          <p className="mt-0.5 text-xs text-rally-subtle">{program.sport}</p>
          {program.description && (
            <p className="mt-1 text-sm text-rally-muted">{program.description}</p>
          )}
        </div>
        <div className="flex shrink-0 gap-2">
          <Button variant="primary" size="sm" onClick={onViewPathway}>
            View Pathway
          </Button>
        </div>
      </div>
    </Card>
  );
}

function Skeleton() {
  return (
    <div className="space-y-3">
      {[0, 1, 2].map((i) => (
        <div key={i} className="h-20 animate-pulse rounded-lg bg-neutral-100 dark:bg-neutral-800" />
      ))}
    </div>
  );
}
