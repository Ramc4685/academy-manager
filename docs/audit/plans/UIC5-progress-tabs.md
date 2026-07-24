# UIC5 — Progress as a tab of student detail / coach session detail
Status: DONE (PR #328, 2026-07-23)
Size: S · Depends on: none (MT5 monolith split benefits later) · Tracker: ../TRACKER.md

## Problem
Skill-progress lives on separate routes one hop away from the detail screens that own the context:
- Admin: `/admin/students/[studentId]/progress` (624L) vs student detail `page.tsx` (3,038L) which already has a tab bar.
- Coach: `/coach/sessions/[id]/skills` (349L) and `/coach/sessions/[id]/progress` (101L) vs session detail (526L) which links out via two buttons.

## Current behavior (verified)
- Student detail `app/(admin)/admin/students/[studentId]/page.tsx`: `STUDENT_TABS` at lines 82-88 — **five** tabs already: `overview | training | sessions | billing | family` (`type StudentTab` line 78, `activeTab` state line 104). (Audit note said overview/billing at :83-100; actual file has 5 tabs at :82-88 — plan updated accordingly.)
- Progress page `app/(admin)/admin/students/[studentId]/progress/page.tsx` (624L): full skill passport/pathway editor (`getStudentProgress`, `placeStudentInLevel`, `recordAdminTestAttempt`, `updateAdminSkillStatus` from `lib/api/curriculum`), supports `?program_id=` and `?return_to=/&return_label=` deep links via `lib/navigation/admin-student-progress-return.ts`. Inbound links built with `buildStudentProgressHref` from **three** files: `admin/students/[studentId]/page.tsx`, `admin/sessions/[id]/page.tsx`, `admin/pathway/progress/page.tsx`.
- Coach session detail `app/(coach)/coach/sessions/[id]/page.tsx`: "Skill updates" / "Skill Progress" buttons at lines 259-270 linking to `skillsHref` / `progressHref` (subroutes carry the `?date=` param).
- MT5 constraint: student detail is a 3,026L monolith — this item must NOT grow it.

## Proposed change (target IA)
**Admin:** keep the `/admin/students/[studentId]/progress` route as the canonical URL, but surface it as a 6th tab "Progress" on the detail tab bar. Two acceptable wirings; choose (a):
(a) *Tab-as-link:* the Progress tab in `STUDENT_TABS` renders as a `<Link>` to `buildStudentProgressHref({studentId, returnTo: current detail URL})` instead of `setActiveTab`, and the progress page renders the same tab bar header with Progress active. Zero monolith growth, no route change, `?return_to` deep-links keep working.
(b) *In-page panel:* lazy-import (`next/dynamic`) a `StudentProgressPanel` component extracted from the progress page. More code motion; only pick if (a)'s header duplication is unacceptable.
**Coach:** same tab-as-link treatment — session detail gets a small tab strip `Attendance · Skills · Progress` where Skills/Progress tabs are links to the existing subroutes (which already exist and carry `?date=`); the two subpages render the same strip. No route deletions, no redirects needed.

## Implementation steps
1. Extract a tiny shared header component `components/admin/StudentDetailTabs.tsx` (tab strip only: takes `active`, `studentId`, renders 5 state-tabs + Progress link-tab). Use it in both the detail page (replacing the inline `STUDENT_TABS` map render) and the top of the progress page. Net monolith delta: negative.
2. Progress page: render `StudentDetailTabs active="progress"`, keep the existing `return_to` back-link as secondary breadcrumb. `SCREEN_META` gains `"/admin/students"` child handling already via `metaForPath` prefix fallback — optionally add an explicit entry.
3. Coach: add `components/coach/SessionDetailTabs.tsx` (Attendance/Skills/Progress link strip preserving `?date=`); render in `sessions/[id]/page.tsx` (replacing the two buttons at :259-270), `sessions/[id]/skills/page.tsx`, `sessions/[id]/progress/page.tsx`.
4. Nav: no `screen-meta.ts` nav changes (Students item `match: startsWith("/admin/students")` already highlights progress). No redirects needed — no routes move.
5. e2e: `admin-students.spec.ts`, `coach-day-hub-passport.spec.ts`, `skill-board.spec.ts` touch these surfaces — update selectors only if the old "Skill updates"/"Skill Progress" button text is asserted; keep testids on the subpages unchanged.

## Files to change / delete
- `frontend/components/admin/StudentDetailTabs.tsx` (new)
- `frontend/app/(admin)/admin/students/[studentId]/page.tsx` (swap inline tab render for shared component; no other growth)
- `frontend/app/(admin)/admin/students/[studentId]/progress/page.tsx` (add tab header)
- `frontend/components/coach/SessionDetailTabs.tsx` (new)
- `frontend/app/(coach)/coach/sessions/[id]/page.tsx`, `.../skills/page.tsx`, `.../progress/page.tsx` (tab strip)
- e2e specs above if button-text selectors break

## Verification
`pnpm typecheck && pnpm lint && pnpm e2e`. Manually: tab strip consistent across detail↔progress; `?return_to` links from `admin/sessions/[id]` and `admin/pathway/progress` still resolve; coach `?date=` preserved across tabs. No routes added/removed → local-auth-inventory / route-matrix manifests and backend unaffected.

## Risks / rollback
- Lowest-risk item in the set: purely presentational wiring, no data or route changes. Rollback = git revert.
- Keep an eye on MT5: do not inline any progress logic into the 3,026L detail page.

## PR checklist
- [x] Release note: "Student and session skill progress now appear as tabs on their detail screens"
- [x] TRACKER.md: UIC5 → DONE + PR link
- [x] This plan: Status → DONE (PR #328, 2026-07-23)
