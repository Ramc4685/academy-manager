# coach experience passport redesign

## Current State

Status: active

## Problem

Design coach home/passport flow so home prioritizes sessions, attendance, skills, parent communication, and teaching guidance; keep coach pay separate; investigate passport 404 path before implementation.

## Changed Files

- None recorded yet.

## Log

- 2026-06-18T20:58:19 main/NA: Task ledger created.
- 2026-06-18T20:59:02 main/working: Brainstorming discovery: coach dashboard currently shows Expected cut on Home, conflicting with Wave 1A coach Today no-payment intent and user direction. Coach passport backend route and frontend client both exist at /api/v2/coach/students/{student_id}/passport, so observed browser 404 likely involves the running BFF/proxy/backend instance or deployment freshness rather than absent source code. Existing teaching-plan and skill-board work can support a coach home focused on sessions, attendance, skills, parent communication, and what to coach; coach pay should move to a separate tab.
- 2026-06-19T07:41:22 main/working: Brainstorming decision: Coach Home should use a whole-day overview, not money-first. Each session needs per-student skill gaps/weak spots so the coach can personally train students during that session.
- 2026-06-19T07:42:52 main/working: Brainstorming decision: Session focus should default to grouped-by-skill, so coaches can train several students together. Add a toggle to view top 2-3 skill gaps per student when they need individual coaching detail.
- 2026-06-19T07:44:05 main/working: Brainstorming discovery: direct messaging primitives exist in backend/v2/shared/comms/messages.py and admin routes at /api/v2/admin/messages*, but current source does not show dedicated coach/parent persona inbox routes or UI. Shared /messages page redirects non-admins to workspace. Design should reuse existing message storage/service but add scoped coach/parent BFF/UI instead of inventing unrelated messaging.
- 2026-06-19T07:45:00 main/working: Brainstorming decision: Coach messaging should support both individual parent messages from student/session skill context and session-level parent broadcasts/updates, with individual messaging primary and broadcast secondary.
- 2026-06-19T07:45:54 main/working: Brainstorming decision: Coach pay belongs under Profile as Pay & statements. Do not add a Pay bottom tab and do not show expected cut/pay metrics on Coach Home.
- 2026-06-19T07:46:57 main/working: Brainstorming decision: Keep the coach Skill Passport page as full per-student detail and fix the current loading/404 path. Session skill focus remains the default session workflow, with passport as full drill-down.
- 2026-06-19T07:49:22 main/working: Brainstorming decision: Coach self-attendance scope is absence notice only. Coach can mark I can't attend before a session so admin knows to find a replacement coach; do not add coach self-present check-in in this slice.
- 2026-06-19T07:52:14 main/working: Brainstorming approval: Coach Day Hub UI structure accepted. Home shows whole-day summary, session cards with grouped skill gaps, attendance/messages/absence actions, and no pay metrics.
- 2026-06-19T07:53:13 main/working: Brainstorming update: Coach Day Hub must support navigation to future sessions, not only today. Include previous/next date, Today/Tomorrow/This week/calendar controls, and future session preview with teaching plan, parent messaging, and absence notice.
- 2026-06-19T07:55:09 main/working: Brainstorming approval: rich date-aware Coach Day Hub mockup accepted. Keep detailed session cards and add date controls at the top without reducing session skill/action detail.
- 2026-06-19T07:57:25 main/working: Brainstorming update: Session workspace must support skill updates in two modes: by skill group (select one skill and update all relevant students together) and by student (select one student and update that student's skills). This is in addition to viewing grouped gaps and passport drill-down.
- 2026-06-19T07:59:10 main/working: Brainstorming clarification: Skill updating must not happen directly on Coach Home. Home only summarizes skill focus and links into a separate, easy coach session skill-update workspace with by-skill and by-student update modes.
- 2026-06-19T07:59:35 main/working: Brainstorming approval: Skill update separation accepted. Home summarizes and links; separate session skills workspace handles by-skill and by-student updates.
- 2026-06-19T07:59:57 main/working: Brainstorming approval: Data/API section accepted: date-aware day hub read model, separate session skills workspace with bulk-by-skill and by-student updates, passport fix, scoped coach-parent messaging, and future-session absence notice.
- 2026-06-19T08:00:39 main/working: Brainstorming update: Design must reuse the current application/coach theme and design system. Error states must show clean coach-readable messages, not raw API details, stack traces, or route names.
- 2026-06-19T08:08:28 main/working: Spec review change: checked existing prep/skills library code. Coach prep is already coded as /coach/today/plan with lesson cards, teaching details, videos/PDF citation chips, and student focus rows; session detail links Skill Progress. Full lesson-card library management is admin-only under pathway. Spec should explicitly link Day Hub session cards to Prepare/Teaching plan and note that a standalone coach-wide skills library is not currently coded.
## Verification

- No verification recorded yet.

## Reusable Lessons

- None recorded yet.
