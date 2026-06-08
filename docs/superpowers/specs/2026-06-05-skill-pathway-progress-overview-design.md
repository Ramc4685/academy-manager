# Skill Pathway Progress Overview Design

Date: 2026-06-05
Status: Draft for user review

## Goal

Create a thin end-to-end Skill Pathway UI slice that lets admins, coaches, and
parents understand the same progress facts:

- Which level a student is currently in.
- Which skills in that level are complete.
- Which required skills remain.
- Whether the student is ready for testing, level-up recommendation, approval,
  or certificate issuance.

The first implementation should prioritize a shared progress summary contract
and persona-specific presentation, not a large redesign of every pathway page.

## Current UI

The app already has several Skill Pathway surfaces:

- Admin curriculum setup at `/admin/pathway`.
- Admin program/level/skill details at `/admin/pathway/[programId]`.
- Admin one-student progress at `/admin/students/[studentId]/progress`.
- Coach one-student skill passport at
  `/coach/students/[studentId]/passport?program_id=...`.
- Parent child progress at `/parent/progress`.

These screens prove the backend workflows exist, but they are fragmented. There
is no strong operator view that answers, across students, who is at which level
and what needs action.

## Completion Rule

Normal level completion stays strict:

1. A student is placed into a program level.
2. The level has required and optional skills.
3. Coaches may update non-passing skill statuses such as `INTRODUCED`,
   `LEARNING`, `PRACTICING`, `TEST_READY`, and `NEEDS_REVIEW`.
4. A skill becomes `PASSED` only through a recorded test attempt.
5. When every required skill in the current level is `PASSED`, the student is
   level-complete.
6. The coach recommends level-up.
7. Admin approves the recommendation.
8. The system creates the next level progress and issues a certificate.

There is no general "mark level complete" shortcut in the first slice. An admin
override for corrections or migration backfill can be designed later with an
audit reason.

## First Slice

Build a shared progress summary read model and use it in three persona surfaces.

### Shared Summary

The shared summary should include:

- `student_id`
- `student_name`
- `program_id`
- `program_name`
- `current_level_id`
- `current_level_name`
- `current_level_sequence`
- `required_skill_count`
- `required_skills_passed`
- `total_skill_count`
- `total_skills_passed`
- `in_progress_count`
- `not_started_count`
- `test_ready_count`
- `level_completion_status`
- `level_up_status`
- `certificate_count`
- `next_action`

`next_action` should be a small stable enum such as:

- `place_in_level`
- `continue_practice`
- `record_tests`
- `recommend_level_up`
- `awaiting_admin_approval`
- `certificate_issued`

The backend owns these facts. Frontend screens should only format, filter, and
route users to the right workflow.

### Admin Surface

Add an admin overview screen under `/admin/pathway/progress`, with:

- Program selector.
- Filters for level, status, and next action.
- Search by student name.
- Summary metrics: placed students, level-complete students, test-ready
  students, pending approvals, certificates issued.
- Table columns: student, current level, mastery, status, next action.
- Row actions: open student progress, open skill passport/read-only detail, view
  certificates.

This screen answers the academy owner question: "which student is at which level
and what have they completed?"

### Coach Surface

Update the coach session progress view to use the same summary facts for the
students in a session:

- Current level.
- Required skills passed.
- Test-ready count.
- Whether level-up can be recommended.
- Button/link to the existing passport for skill-level work.

The coach still completes skills from the passport by recording tests. The
session list should highlight which students need coach action today.

### Parent Surface

Update the parent progress page to use the same summary facts in a friendly
card:

- Child name.
- Program and current level.
- Required skills mastered count.
- Plain-language status.
- Certificates, if any.
- Link or expansion to the existing skill list.

Parent copy should avoid internal terms like `TEST_READY` or `RECOMMENDED` and
use readable labels such as "Practicing", "Ready for assessment", "Level
complete", or "Certificate issued".

## Data Flow

The first slice should reuse existing student progress, curriculum, enrollment,
and certificate data. It should not duplicate business truth in the frontend.

Admin overview:

```text
Admin route -> application query -> enrollment student names
            -> student_progress current progress
            -> curriculum level/skill metadata
            -> certificates/recommendations
            -> shared summary rows
```

Coach session progress:

```text
Coach route -> authorized session roster
            -> shared summary query filtered to roster student ids
            -> coach session progress cards
```

Parent progress:

```text
Parent route -> owned children
             -> shared summary query filtered to owned student ids
             -> parent child progress cards
```

## Error And Empty States

- No program selected: show a program selector and no table.
- Program has no levels: explain that admin must configure levels.
- Student not placed: show `place_in_level` as the next action for admin; for
  coach/parent, show a neutral "not started" state.
- No skills in current level: show configuration warning to admin; show neutral
  empty state to coach/parent.
- Backend failure: retain current route-level error cards.
- Unauthorized or unassigned coach access: preserve existing 401/404 behavior.

## Non-Goals

The first slice does not include:

- Station planner UI.
- Curriculum versioning.
- PDF certificates.
- Monthly parent reports.
- Notification fan-out.
- Admin force-complete override.
- A full visual redesign of the entire admin shell.

## Testing

Backend:

- Unit or contract coverage for the shared summary query.
- Tenant isolation coverage for summary rows.
- Coach authorization coverage for session-filtered progress.
- Parent ownership coverage for child-filtered progress.

Frontend:

- Admin overview renders rows, filters, and empty states.
- Coach session progress renders action states and links to passport.
- Parent progress renders friendly status labels.
- Typecheck and lint.

## Route Shape

Use persona-specific BFF routes over one shared application query:

- Admin: `GET /admin/pathway/progress?program_id=...`
- Coach: `GET /coach/sessions/{session_id}/students-progress?program_id=...`
- Parent: `GET /parent/progress/summary?program_id=...`

The shared summary query should live below the interface layer so each route can
apply its own authorization and persona shaping without duplicating business
logic.
