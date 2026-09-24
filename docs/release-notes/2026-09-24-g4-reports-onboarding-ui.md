# Attendance risk and families lost reports, owner setup checklist, run-4 UI leftovers, messaging design note

PR: #964

## What changed

- **Attendance risk and families lost reports (L5b):**
  - Two read-only cards in the People group on `/admin/reports`.
  - Attendance risk groups at-risk students by class and by coach.
  - Families lost counts Left families in a date window (default: last 90 days), grouped by departure reason.
  - Both are for admins, not owner-only, and carry no money.
- **Owner setup checklist (L7):**
  - A new `GET /api/v2/admin/setup-checklist` powers a "Set up your academy" card on the admin dashboard.
  - It derives nine steps from existing settings. Each open step links to where it is done. The card disappears once every step is done.
  - New runbook: `docs/runbooks/onboard-academy-two.md`.
- **Run-4 UI leftovers (UI-7):**
  - Month close starts collapsed on every viewport.
  - Scroll cues on the People filters and Settings tabs.
  - One teaching-plan link on coach Today.
  - WCAG AA contrast fixes.
  - Student and family cross-links styled as links.
  - Small copy fixes.
- **App-sent SMS and WhatsApp design note (L12):** design document only, no code.

## Deploy notes

- **Migrations:** none. No migration ids ship in this PR. The families-lost report reads through the existing 0090 index.
- **Owner steps:** none are needed to deploy. After deploy, the owner can use the dashboard setup card to finish any open steps. The open decisions in the L12 design note are not needed for this deploy.
- **Config:** no new environment variables, secrets or feature flags.

## Risk / rollback

- **Risk:** low.
  - The new endpoints are read-only, admin-gated and tenant-scoped.
  - The setup checklist returns status only (no amounts or account ids), and reports `unknown` when a source fails instead of erroring.
  - The UI changes are presentational.
- **Rollback:** revert this PR and redeploy. No data or schema changes to undo.
