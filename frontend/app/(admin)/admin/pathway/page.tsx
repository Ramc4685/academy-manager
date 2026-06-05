"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  createProgram,
  listPrograms,
  seedBadminton,
  type Program,
} from "@/lib/api/curriculum";
import { getActiveAcademyId } from "@/lib/api/client";
import { Card } from "@/components/ds/card";
import { Button } from "@/components/ds/button";

export default function AdminPathwayPage() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const academyId = getActiveAcademyId() ?? "";

  const { data: programs, isLoading, isError } = useQuery({
    queryKey: ["admin", "programs", academyId],
    queryFn: () => listPrograms(academyId),
    enabled: Boolean(academyId),
  });

  const [showForm, setShowForm] = useState(false);
  const [formName, setFormName] = useState("");
  const [formSport, setFormSport] = useState("");
  const [formDescription, setFormDescription] = useState("");

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
    mutationFn: (programId: string) => seedBadminton(programId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["admin", "programs"] });
    },
  });

  const list = programs ?? [];

  return (
    <section data-testid="admin-pathway" className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold">Skill Pathways</h1>
          <p className="mt-0.5 text-sm text-neutral-500">
            Programs and their learning levels
          </p>
        </div>
        <Button
          variant="primary"
          size="sm"
          onClick={() => setShowForm((v) => !v)}
        >
          {showForm ? "Cancel" : "Create Program"}
        </Button>
      </div>

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
                placeholder="e.g. Junior Badminton"
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
              <p className="text-xs text-red-600">Failed to create program. Please try again.</p>
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
        <p className="text-sm text-neutral-500">No programs yet. Create one to get started.</p>
      ) : (
        <div className="space-y-3">
          {list.map((program) => (
            <ProgramCard
              key={program.program_id}
              program={program}
              seedPending={seedMutation.isPending}
              onViewPathway={() =>
                // eslint-disable-next-line @typescript-eslint/no-explicit-any
                router.push(`/admin/pathway/${encodeURIComponent(program.program_id)}` as any)
              }
              onSeedBadminton={() => seedMutation.mutate(program.program_id)}
            />
          ))}
        </div>
      )}
    </section>
  );
}

function ProgramCard({
  program,
  seedPending,
  onViewPathway,
  onSeedBadminton,
}: {
  program: Program;
  seedPending: boolean;
  onViewPathway: () => void;
  onSeedBadminton: () => void;
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
          <Button
            variant="secondary"
            size="sm"
            disabled={seedPending}
            onClick={onSeedBadminton}
          >
            Seed Badminton
          </Button>
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
