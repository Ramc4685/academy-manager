# Post-MVP Skill Pathway — Backlog

Tickets to schedule **after** the Skill Pathway MVP merges. These are
deliberately not built in the MVP (see [ADR-0010](../adr/0010-skill-pathway-module.md)).
Each item is a ticket stub — refine into a tracked issue before picking up.

> Status: backlog (not started). Do not implement as part of the MVP merge.

---

## 1. Curriculum versioning
**Problem:** Editing a program/level/skill mutates the live curriculum in place.
A student placed under "v1" sees later edits retroactively, and certificates
reference whatever the level says *now*.
**Scope:** Immutable curriculum versions; pin a student's progress + issued
certificates to the version active at placement/issue time; admin "publish new
version" flow.
**Notes:** Interacts with #7 (certificates should capture the version).

## 2. Student assessment workflow
**Problem:** Test attempts are recorded ad hoc by a coach. There is no
structured "assessment session" (schedule an assessment, capture multiple
skills in one sitting, sign-off).
**Scope:** Assessment entity grouping multiple skill tests; coach assessment
screen; optional second-coach verification.

## 3. Skill prerequisites
**Problem:** Within a level, skills are independent. Some skills should require
others first (e.g. "grip change" before "net shot").
**Scope:** Prerequisite edges between skills; enforce/advise ordering in the
coach passport UI; surface "blocked" skills.

## 4. Progress timeline
**Problem:** Progress is shown as current state only. There is no historical
timeline of when skills were introduced/passed or when levels completed.
**Scope:** Read model over the immutable `test_attempts` /
`student_skill_progress` history (ADR-0010 #9); timeline UI for parent + admin.

## 5. Station planner UI
**Problem:** ADR-0010 #3 defined the `ClassPlan` / `Station` data model but
deferred the UI. Coaches cannot yet plan station-based classes.
**Scope:** Station planner screen; assign skills/students to stations; rotation
timing. Backend data model already scoped.

## 6. Parent monthly reports
**Problem:** Parents only see live progress. No periodic digest.
**Scope:** Monthly per-student progress summary (skills passed, levels reached,
certificates earned); email/PDF delivery. Depends on #8 for delivery.

## 7. Better certificates
**Problem:** MVP certificates are JSON records (ADR-0010 #4) and the approve
route does **not** populate `student_name` / `level_name` / `program_name`, so
issued certificates currently have blank display fields (see ADR-0010 #10 and
the stabilization report). No PDF/printable output.
**Scope:**
- Populate certificate display fields at issue time (look up student name from
  the enrollment/admin directory and level/program names from curriculum). This
  is the purposeful re-introduction of the student/level/program lookup removed
  in the MVP cleanup.
- Generate a printable/PDF certificate artifact.
- Capture curriculum version (#1) on the certificate.

## 8. Notifications
**Problem:** ADR-0010 #7 emits domain events to the outbox but does no fan-out.
Coaches/parents/admins are not notified of level-up recommendations,
approvals, or certificate issuance.
**Scope:** Consume student_progress domain events; notify the relevant persona
(in-app + email). Foundation for #6 delivery.

## 9. Coach session-progress page calls an admin-only endpoint (bug)
**Problem:** `frontend/app/(coach)/coach/sessions/[id]/progress/page.tsx` loads
per-student progress via `getStudentProgress()`
(`frontend/lib/api/curriculum.ts`), which targets
`GET /admin/students/{student_id}/progress`. That route is guarded by
`require_persona("admin")` (`backend/v2/interfaces/admin/progress_routes.py`),
so a coach token is rejected and the per-student progress cards fail to load for
real coaches. The session **roster** call (`GET /coach/sessions/{id}/roster`)
is correct; only the per-student progress call is wrong-persona.
**Scope (P2.1):** Add a coach-scoped per-student progress endpoint — e.g.
`GET /coach/sessions/{session_id}/students-progress` (or
`GET /coach/students/{student_id}/progress`) reusing `GetSessionRoster` +
`GetStudentProgress`/`get_passport`, behind the **coach-assignment guard**
(the same guard P0.1 adds to the coach skill routes), then repoint the frontend
helper. **Deferred from this pass** to avoid colliding with the in-flight P0.1
coach-authorization branch and the P1.1 composition wiring, both of which are
actively editing the coach routes/composition. Promote to P1 when those land.

---

## Accepted contract decisions (not tickets)

- **P2.2 — `InsufficientTestData`:** `RecordTestAttemptCommand` enforces
  `attempts_count` via pydantic `Field(ge=1)`, so an empty/zero-attempt request
  is rejected with **HTTP 422** at the schema boundary. We **accept the 422 as
  the contract** rather than introducing a dedicated `InsufficientTestData`
  domain error — the 422 already prevents the invalid state and a custom 4xx
  adds no behavioural value. Revisit only if a clearer client-facing message is
  required.
