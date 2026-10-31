import type {
  AdminStudentWaiverRow,
  AdminWaiverProgram,
  AdminWaiverTemplateManagementView,
} from "@/lib/api/admin";

/** Where a waiver's "Required for" line comes from: one waiver, plus the academy's programs. */
export function requiredForLabel(
  template: Pick<AdminWaiverTemplateManagementView, "required" | "scope" | "program_ids" | "assigned_to_registration">,
  programs: ReadonlyArray<AdminWaiverProgram>,
): string {
  // Rows from before assignment only carry the registration flag.
  const required = template.required ?? template.assigned_to_registration;
  if (!required) return "Not required";
  if (template.scope !== "programs") return "All families";
  const known = new Map(programs.map((program) => [program.program_id, program]));
  const labels = (template.program_ids ?? []).map((id) => {
    const program = known.get(id);
    if (!program) return "Removed program";
    return program.archived ? archivedProgramLabel(program.name) : program.name;
  });
  return labels.length > 0 ? labels.join(", ") : "No programs chosen";
}

/** How a program that is archived but still assigned to a waiver reads. */
export function archivedProgramLabel(name: string): string {
  return `Archived: ${name}`;
}

/** Short, plain status line for one waiver on the admin student page. */
export function studentWaiverSummary(row: AdminStudentWaiverRow): string {
  if (row.status === "signed") {
    return `Signed${row.signed_version ? ` v${row.signed_version}` : ""}`;
  }
  if (row.status === "older_version") {
    return `Signed an older version${row.signed_version ? ` (v${row.signed_version})` : ""}`;
  }
  return "Not signed";
}

/** Rows staff should be warned about: every waiver that is not signed at its live version. */
export function unsignedStudentWaivers(
  rows: ReadonlyArray<AdminStudentWaiverRow>,
): AdminStudentWaiverRow[] {
  return rows.filter((row) => row.status !== "signed");
}
