# People CRM family record: Overview, Details, Billing and Timeline tabs

PR: #933

## What changed

- A family's page (`/admin/families/{id}`) is now the People CRM family record (engineering-spec §4) with four tabs: Overview, Details, Billing and Timeline. The tab lives in `?tab=`, so a link to a family's Billing opens Billing and a reload keeps the tab. No new route. The student page's "Open family billing" link now opens `?tab=billing`.
- Overview shows the family's stage, the number of children, autopay state and, for staff who may see money, the balance. The stage and children come from the same family index row the Families list shows, read through the new `GET /api/v2/admin/families/{id}/record` (admin only; money through the existing `can_view_family_money` check; 404 for a family outside the academy).
- Details is read-only: the parent's name, email and phone from their account, and the children. The second-parent "Gets notices" and "Gets invoices (opted in)" switches are shown turned off and disabled, with a note that they arrive with family contacts. Nothing is sent to a second adult.
- Billing is the existing family billing page, unchanged: same actions, dialogs, reasons and owner-only money actions (charge, refund, void, discounts stay owner-only). Record payment still opens a dialog with the amount, method and an explicit Record payment button. The timeline moved to its own Timeline tab and is unchanged.
- Each child opens a side panel with their classes, recent attendance, the coach notes a coach chose to share with the family (the same notes the parent already sees, with the coach's name), and an "Open full page" link to the student page. New read: `GET /api/v2/admin/students/{id}/coach-notes` (admin only; private notes never appear; 404 for a student outside the academy).
- Attendance can be corrected from the panel. Correct opens a choice of the other statuses and an optional reason; Review shows exactly what changes ("Change Kid's Sep 12 mark from Present to Absent?") and only the Confirm button saves. It uses the existing admin correction route (`PATCH /api/v2/admin/session-occurrences/{occurrence_id}/attendance/{student_id}`): no 24-hour window for admins, and the mark keeps who corrected it, the previous status, the reason and the time. Focus goes back to the corrected row after saving and to the child's row when the panel closes.
- The student detail's recent attendance rows now include `occurrence_id`, `previous_status` and `corrected_at` (added fields).

## Deploy notes

- Backend and frontend ship together. The frontend reads the two new admin routes; with an older backend the Overview and Details show what the billing read provides and the panel shows "could not be loaded" for coach notes.
- No migration, no index, no feature flag, no environment variable.

## Risk / rollback

- Low. Everything new is a read except the attendance correction, which reuses the #517 admin route and its audit trail unchanged. Tests pin that another academy's occurrence or student is a 404 and that the correction is stored on the academy's own row with the admin and previous status.
- Visible change: opening a family now lands on Overview instead of the billing page; links from money screens still open the family and Billing is one click (or `?tab=billing`).
- Not built yet: Hold child and Change class in the child panel (use Open full page), editable family details and second-parent contacts (Phase 4), and coach notes in the Timeline.
- Rollback: revert the PR. The two read routes are unused without the page.
