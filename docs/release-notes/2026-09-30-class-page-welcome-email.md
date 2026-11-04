# Class page: Roster first, Welcome email tab, coach contact default

PR: #1026

## What changed

- **Class page layout.** Roster opens first on every screen. Tabs are now Roster, Class dates, Waitlist, Teaching plan, Welcome email. The Class dates content (add/change replacement, cancel date, attendance, show all) moved into its tab with the same test ids. Coaching staff is a one-line strip under the header (lead coach, assistants, "Edit assistants"). The Hide/Show context cards and their per-device remembered state are gone.
- **Welcome email tab** replaces the Communication pack card and the "Edit communication pack" button. Seven rows: WhatsApp link, venue, parking, what to bring, arrive early, coach contact, absences and make-ups. Each shows the class's own value (tag "This class", with Reset) or the academy default in grey (with Override), or "Not set". An arrival of 0 or blank reads "Not set". One Save sends only the changed pack fields through the existing `PATCH /admin/sessions/{id}` (explicit null clears a field); schedule, coach, seats and price are never sent.
- **Preview email.** New read-only `GET /admin/sessions/{id}/welcome-email-preview` renders the real enrollment welcome email for the class with a sample student name and returns `{subject, html}`. It sends nothing and writes nothing. The tab shows it in a sandboxed iframe (no scripts).
- **Coach contact academy default.** New `default_coach_contact_policy` on the academy record, editable in Settings > Academy profile > Class defaults. The welcome email uses it when the class's own coach contact is blank; the class value wins.
- **Public page venue fallback.** A class with no venue address of its own shows the academy's default venue address on the public page.

## Deploy notes

- No migration. `default_coach_contact_policy` is read with a default of none, so existing academy documents read as before.
- BLNO classes already carry their own values, so BLNO's welcome emails and public page are unchanged until an admin sets an academy default.
- New API surface: one admin GET route; `AdminAcademyView` and `UpdateAdminAcademyRequest` gain `default_coach_contact_policy`.
- Removed the unused `lib/use-persisted-open.ts` hook (only the old context cards used it).

## Risk / rollback

- Main risk: the Class dates table is one click further away on the class page. Existing e2e specs were updated to open the tab first.
- The Edit session dialog still edits the pack until the sibling lane removes it from that dialog; both write the same fields.
- Rollback: revert this PR. No data changes are made by it.
