"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";

import { ProgramEditor } from "@/components/admin/curriculum/program-editor";
import { ProgramList } from "@/components/admin/curriculum/program-list";

/**
 * Settings -> Curriculum (Settings overhaul Phase 3 PR 11): the Pathway
 * authoring UI, moved as-is. The program editor opens in the tab via
 * `?program=<id>`; clearing that param is "back" to the list.
 */
export function CurriculumPanel() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const programId = searchParams.get("program");

  function go(next: string | null) {
    const params = new URLSearchParams(searchParams.toString());
    params.set("panel", "curriculum");
    if (next) params.set("program", next);
    else params.delete("program");
    router.push(`${pathname}?${params.toString()}` as never, { scroll: false });
  }

  return (
    <section data-testid="admin-settings-curriculum" className="space-y-6">
      {programId ? (
        <ProgramEditor programId={programId} onBack={() => go(null)} />
      ) : (
        <ProgramList onOpenProgram={(id) => go(id)} />
      )}
    </section>
  );
}
