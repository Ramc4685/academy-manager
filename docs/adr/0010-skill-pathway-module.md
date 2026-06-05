# ADR-0010: Skill Pathway Module

**Status:** Accepted  
**Date:** 2026-06-05  
**Deciders:** Engineering

## Context

Students at the academy progress through levels. The existing system does not track skill mastery — only attendance and billing. This ADR captures decisions for the Skill Pathway Module (MVP).

## Decisions

1. **Tenant-owned curriculum.** Programs, levels, and skills are scoped to `academy_id`. Each academy configures its own pathway. No platform-global curriculum.

2. **Two new bounded contexts.** `curriculum` owns programs/levels/skills/criteria. `student_progress` owns tracking, test attempts, certificates, and level-up workflow. Class delivery additions go into the existing `coaching` context.

3. **MVP skips station-based class planning UI.** The data model is defined (`ClassPlan`, `Station`), but the UI is deferred.

4. **Certificates are JSON records.** No PDF library in MVP. A certificate document is issued after level-up approval.

5. **BWF Shuttle Time PDFs are reference only.** Zero BWF lesson text enters source code, seed data, DB, or UI. `ExternalLessonReference` stores only: source name, module name, lesson range, short reference title, page hint, internal note.

6. **Level-up flow.** Default rule: all required skills PASSED + coach recommendation. Admin approval is optional per program config (`requires_admin_approval`).

7. **Notifications are stubs.** Domain events are emitted to the outbox. Notification fan-out is deferred.

8. **Student self-view is out of MVP scope.** Parent view covers student progress.

9. **History is immutable.** `test_attempts` and `student_skill_progress` are never deleted.

## Consequences

- New collections: `skill_programs`, `skill_levels`, `skills`, `skill_criteria`, `external_lesson_refs`, `student_level_progress`, `student_skill_progress`, `test_attempts`, `level_up_recommendations`, `skill_certificates`, `coach_skill_notes`.
- All collections lead with `academy_id` in indexes (ADR-0006 compliance).
- Cross-context integration via IDs and Protocol adapters only.
- Domain logic (pass calculation, level completion check) is a pure function with no I/O.
