export function coachDayHubPath(date?: string): string {
  return withParams("/coach/day-hub", date ? { date } : {});
}

export function coachSessionSkillsPath(
  occurrenceId: string,
  options: { date?: string; programId?: string } = {},
): string {
  return withParams(`/coach/sessions/${encodeURIComponent(occurrenceId)}/skills`, {
    date: options.date,
    program_id: options.programId,
  });
}

export function coachSessionBulkSkillStatusPath(occurrenceId: string): string {
  return `/coach/sessions/${encodeURIComponent(occurrenceId)}/skills/bulk-status`;
}

export function coachStudentPassportPath(studentId: string, programId?: string): string {
  return withParams(`/coach/students/${encodeURIComponent(studentId)}/passport`, {
    program_id: programId,
  });
}

export function coachSkillNotesPath(studentId: string, skillId?: string): string {
  return withParams(`/coach/students/${encodeURIComponent(studentId)}/skill-notes`, {
    skill_id: skillId,
  });
}

function withParams(path: string, params: Record<string, string | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value) search.set(key, value);
  }
  const query = search.toString();
  return query ? `${path}?${query}` : path;
}
