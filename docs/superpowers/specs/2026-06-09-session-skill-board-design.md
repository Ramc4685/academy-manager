# Session Skill Board Design

Date: 2026-06-09
Status: Approved direction (skill board + quick pass), spec under user review

## Goal

Give admins and coaches one glanceable, tap-to-update view of skill progress for
a session: which level each student is in, which skills inside that level are
complete, and what each student needs next — without navigating into one
student page at a time.

Approved decisions:

- Approach: session skill board (students × skills matrix per session), not a
  roster row expansion and not the read-only academy overview.
- Quick pass: one-tap pass records a 1/1 test attempt attributed to the caller.
  The domain rule "PASSED only via recorded test attempt" is unchanged.

## Hard Constraints

1. **BFF + DDD boundaries (no deviation).**
   - New routes are persona-shaped under `backend/v2/interfaces/admin/` and
     `backend/v2/interfaces/coach/`. No generic CRUD.
   - Interfaces call application use cases only. No Mongo access, no
     infrastructure imports, no domain imports from interface modules.
   - The shared read model lives in
     `backend/v2/contexts/student_progress/application/`; business rules stay
     in `domain/`; Mongo reads stay in `infrastructure/` behind ports.
   - No cross-context domain imports. Roster/student-name resolution follows
     the existing composition pattern used by
     `get_session_students_progress` (coach) and the admin progress overview
     (lookup adapters / BFF-layer composition, typed via Protocols).
   - Tenant identity resolves explicitly per request; all new reads are
     tenant-scoped through `TenantScopedRepository`; no `default_academy_id`
     in SaaS paths. Tenant isolation tests required for the new reads.
   - Wrong-persona access must not leak data existence (existing 401/404
     behavior preserved).
2. **Mobile-first coach experience.** Coaches update during training on a
   phone. The coach surface is designed for one-hand, court-side use:
   - No hover interactions; everything is tap.
   - Tap targets ≥ 44px.
   - The cell editor is a bottom sheet on small screens, popover on desktop.
   - "By skill" mode is the primary mid-class flow: pick the drill's skill,
     tap each student as you assess.
   - Optimistic updates with clear pending/failure states so a slow court
     network never blocks the coach.

## Current State (already on main)

- Per-student update pages exist for both personas:
  `frontend/app/(admin)/admin/students/[studentId]/progress/page.tsx` and
  `frontend/app/(coach)/coach/students/[studentId]/passport/page.tsx`.
- Backend mutations exist and are reused as-is:
  - Admin: `POST /admin/students/{sid}/skills/{skill_id}/status`,
    `POST .../skills/{skill_id}/test`, place-in-level, level-up approve/reject.
  - Coach: status update, test record, level-up recommend, skill notes
    (`backend/v2/interfaces/coach/skill_routes.py`).
- Session-level summaries exist:
  `GET /coach/sessions/{session_id}/students-progress` and the admin
  pathway progress overview query.
- Gap: no per-skill detail across a roster, and updating requires per-student
  page navigation — impractical mid-class, which is why progress stays at 0/N.

## Design

### Backend — one new read model, zero new mutations

New application query in `student_progress`:
`GetSessionSkillBoard` (`application/use_cases/get_session_skill_board.py`).

Persona routes over the shared query:

```txt
GET /api/v2/admin/sessions/{session_id}/skill-board?program_id=...
GET /api/v2/coach/sessions/{session_id}/skill-board?program_id=...
```

- Coach route reuses the existing assigned-to-session authorization used by
  `get_session_students_progress`.
- Admin route resolves the roster via the existing admin enrollment listing
  composition (BFF layer composes enrollment + student_progress use cases; no
  cross-context domain imports).

Response shape (persona DTO shaped at the BFF layer; values synthetic):

```jsonc
{
  "program_id": "...",
  "program_name": "...",
  "groups": [            // one group per current level (handles mixed levels)
    {
      "level_id": "...",
      "level_name": "Grip and Control",
      "sequence": 1,
      "skills": [
        { "skill_id": "...", "name": "...", "sequence": 1, "is_required": true }
      ],
      "students": [
        {
          "student_id": "...",
          "student_name": "...",
          "statuses": {
            "<skill_id>": {
              "status": "PRACTICING",
              "last_updated_at": "2026-06-08T17:00:00Z"
            }
          },
          "required_passed": 2,
          "required_total": 5,
          "total_passed": 2,
          "total_count": 6,
          "level_up_status": null
        }
      ]
    }
  ],
  "unplaced": [ { "student_id": "...", "student_name": "..." } ]
}
```

Port addition (batch read, avoids N+1):

- `SkillProgressRepository.list_for_students(student_ids, level_id)` —
  Protocol method in `student_progress/application/ports.py`, implemented in
  `infrastructure/mongo_skill_progress_repo.py` via `TenantScopedRepository`
  helpers. Existing indexes lead with `academy_id` (ADR-0006); add an index
  migration only if query profiling shows the existing
  student/level index is insufficient.

Mutations: none added. Quick pass calls the existing test-attempt endpoint
with `attempts_count=1, success_count=1` and a fixed note marker
(e.g. "Quick pass") so it is auditable in the attempt history.

### Frontend — shared board component, persona adapters

- `frontend/components/pathway/skill-board.tsx`: presentation-only shared
  component. Data and mutation callbacks are injected, so admin and coach pass
  their own typed API clients from `frontend/lib/api/curriculum.ts`
  (extended with the two new board fetchers). The component owns no business
  rules — backend owns truth (status enum, level-up readiness flags come from
  the API).
- React Query: board query per session; optimistic cell update on status
  change/quick pass, invalidate on settle.

Admin surface (desktop-leaning, mobile still works):

- Dedicated sub-route `/admin/sessions/[id]/skill-board` rendering the board
  (the existing session detail page is already large; keep it lean). The
  roster's "x/y skills" text becomes a link to this route.
- Unplaced students render with an inline "Place in level" action (existing
  endpoint + existing form pattern).
- Rows where all required skills are PASSED show a "Ready" badge; pending
  recommendations deep-link to the existing level-up queue.

Coach surface (mobile-first):

- `/coach/sessions/[id]/progress` upgrades to the board with a segmented
  control: **By student** (default list, like today, but expandable per
  student) and **By skill** (drill mode: one skill selected, roster listed,
  one tap per student opens the editor sheet).
- Desktop coach (≥ md breakpoint) renders the same matrix grid as admin.
- Cell editor (bottom sheet on mobile / popover on desktop):
  - Status chips: Introduced · Learning · Practicing · Test ready · Needs review
  - `Quick pass (1/1 test)` primary action
  - `Record test…` expands the existing attempts/successes/notes form
  - Coach-only: add skill note (existing skill-notes endpoint)
- When all required skills pass: "Recommend level up" action in the student
  row (existing endpoint).

### Edge and error states

- Session has no pathway program: program selector fallback (same pattern as
  existing pages).
- Level with no skills: configuration warning for admin; neutral empty state
  for coach.
- Student not placed: listed under "Not placed" — admin gets place-in-level,
  coach sees a neutral hint.
- Backend failure: route-level error card (existing pattern); failed optimistic
  update rolls back the cell and shows a retry affordance.
- Coach not assigned to session: existing 401/404 behavior, no data leak.

## Testing

Backend:

- Interface tests for both new routes: happy path, mixed-level grouping,
  unplaced students, tenant isolation (cross-academy read returns nothing),
  coach-not-assigned authorization, wrong-persona non-leakage.
- Use-case/contract coverage for `GetSessionSkillBoard` and the new port
  method.
- Quick-pass flow already covered by existing test-attempt tests; add one
  assertion that a 1/1 attempt transitions a skill to PASSED end to end.
- `lint-imports --config pyproject.toml` must stay green (layer boundaries).

Frontend:

- `pnpm typecheck` and `pnpm lint` clean.
- Component-level rendering states (loading/error/empty/groups) per existing
  frontend test conventions.
- One Playwright smoke: open coach board on a mobile viewport, by-skill mode,
  tap a student, quick pass, see the cell turn passed.

Record results in the active test ledger per project convention.

## Non-Goals

- Academy-wide `/admin/pathway/progress` overview page (June 5 design; its
  backend query exists and can ride along later).
- Station planner, skill prerequisites, curriculum versioning, PDF
  certificates, notifications, parent surface changes.
- Offline queueing of updates (PWA offline write support is out of scope;
  optimistic UI + retry only).
