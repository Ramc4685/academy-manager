# Shared skill status chip across progress surfaces

## What changed
- One shared `SkillStatusChip` and label map now render skill status on student progress, parent progress, coach passport, coach session skills, the coach teaching focus row and the pathway skill board.
- Student and parent screens now use the same words as coaches and admins ("Passed", "Test ready") instead of "Mastered" / "Almost there".
- Status colours use design-system status tokens only, each checked for WCAG AA contrast.
- Admin student progress and the skill-cell editor read labels from the same map; the admin row keeps its status select as the only status display.

## Deploy notes
- Frontend only. No migrations, no backend changes, no owner steps.

## Risk / rollback
- Low risk: presentation only, no data or API changes. The visible wording change for students and parents is the main user-facing effect.
- Rollback: revert this PR and redeploy the frontend.

PR: #943
