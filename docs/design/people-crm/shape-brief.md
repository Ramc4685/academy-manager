# People CRM: shape brief (confirmed inputs, 2026-09-19)

Target: `docs/design/people-crm/people-crm-prototype.html`, a single-file clickable prototype published as a private artifact at https://claude.ai/artifact/FmvsGLVv1pv9yk1mSbpLYX. Visual authority: DESIGN.md (Rally). Product truth: PRODUCT.md. Mode: Operate. Last critique: 27/40 (`.impeccable/critique/`).

## 1. Job and audience
- An admin **team with roles** (owner, billing, front desk) runs family relationships for a racquet-sports academy of about 60 students.
- They work **about equally on a phone at the gym and a laptop at a desk**. Neither layout is secondary. Phone: Today queue, lookups, log a contact, add a walk-up lead one-handed. Desk: dense sortable tables, bulk actions, billing, follow-up planning, reports.
- Most parent contact happens **outside the app**: WhatsApp, calls and SMS from staff phones, email, in person. The app only sends email.

## 2. Outcome and proof
- Everything about a family in one place, and nothing about a family lives only in someone's head or phone.
- Success: staff can answer "what is going on with this family and who is handling it" in one screen, and a new inquiry never gets lost between WhatsApp and enrollment.
- Product-specific truth to keep: a family is one parent account today; attendance is by class date; holds change the next invoice; trials are marked Came or Didn't come.

## 3. Selected direction
Keep the Rally world and the existing Today queue, reason-driven primary action and preview-before-send. Structural thesis: **People is a section with five views over one family index, and the family record is where contact gets logged.**

## 4. Scope
Clickable prototype, fictional data, single HTML file. No production code.

**Rename:** the academy shown must be fictional (PRODUCT.md forbids the real tenant's name). Use "Riverside Badminton" and title the page "People CRM Prototype". Remove every string that names the real tenant, including example URLs and staff names that identify the real owner; use staff "Maya (owner)", "Jon (billing)", "Tess (front desk)".

**People section (sub-nav under People):**
1. **Today** (default). As now. Add an assignee avatar/initials per row and a Mine / Everyone switch.
2. **Families.** Scope tiles Active, Leaving, Left only. Desk: sortable columns (balance, last contact, next follow-up), tags column, bulk select with Message, Add tag, Export. Groups: saved filters such as "Sat Advanced parents", "Overdue with no card"; a group message shows the recipient count and who is skipped (no email) before sending.
3. **Students.** As now, respecting the scope and class filter.
4. **Pipeline.** Board with columns Inquiry, Trial booked, Trial done, Registered, Enrolled. Card: parent, child and age, source, lead age in days, last contact, next step, assignee. Sources: **WhatsApp or phone** and **Referral** (records which current family referred them) are the two real ones; keep "Other". Cold after 14 days without contact. Quick add lead from a phone: name, phone, child, source. Move a card by buttons, not drag only. On a phone the board becomes a stage switcher with a list.
5. **Follow-ups.** All follow-ups across families: Overdue, Today, Upcoming, Done. Mine / Everyone, reassign, due date, link to family. Auto-created ones (trial passed with no registration, card declined) are labelled as automatic.
6. **Reports** (linked from People, not a nav item): Inquiry to enrolled by source; Families lost and why, by month, with how long they stayed; Attendance risk by class and coach; Money owed by age (1 to 30, 31 to 60, older). Money report hidden from staff without billing permission. Small, honest charts; every number links to the list behind it.

**Family record tabs:** Overview, Details, Messages, Billing, Timeline.
- **Details** replaces Account: primary parent; **family contacts** list (name, relationship, email, phone, gets emails, can pick up); home address; preferred channel; how they heard about us and referrer; tags; login and invite state. Inline edit with field-level errors.
- **Messages:** one thread per family mixing app emails, and staff-logged WhatsApp, SMS, calls and in-person talks, each with author and time. Compose picks a channel: Email sends from the app after a preview; WhatsApp and SMS open the staff member's own app with the text pre-filled (wa.me / sms: links) and then ask "Did you send it?" to log it. "Log a call" and "Spoke in person" are one-tap with a short note. Saved templates.
- **Overview:** keeps children first, money owed, follow-ups with assignee, pinned notes, recent activity. Adds last contact and who.
- **Left families:** reason for leaving, date, time with the academy, and a win-back follow-up.

**Real forms:** Add family, Add inquiry, Add child, Add contact. Duplicate warning when a phone or email already exists, with "Open existing family".

**Permissions shown in the prototype:** a "Viewing as" switch (Owner, Billing, Front desk). Front desk sees an "Owes money" flag with **no amounts**, no Billing tab, no Record payment, no money report. Billing and owner see everything.

Untouched: the phased build plan and decisions sections stay, updated for the new scope.
Anti-goals: no drag-only interactions, no dashboards of vanity metrics, no dot-colour-only meaning, no nested cards, no fake SMS sending, no real tenant data.

## 5. States and ranges
About 60 students, 40 families, 5 to 15 open leads, 3 staff. Names up to 30 characters, 1 to 4 children per family, 0 to 3 extra contacts, 0 to 20 tags in total. Material states: empty pipeline, empty follow-ups ("Nothing due"), brand-new family with no children, lead with no email, duplicate on add, failed email send with retry, message not logged after handoff, no permission, all clear on Today, search with no results, long names and long notes.

## 6. Interaction and layout
- Desk: sub-nav as tabs under the People title; tables are dense and sortable; record uses two columns on Overview and Details.
- Phone: sub-nav is a scrollable strip; pinned bottom action bar on the record; Pipeline as stage switcher; forms full-screen sheets; 44px targets.
- Feedback: every write confirms with a toast and Undo where reversible; previews before anything reaches a parent; errors sit next to the field, never toast-only.
- Keyboard and screen reader: keep focus traps, arrow-key tabs and menus, row open semantics; "/" search on desk only.

## 7. Constraints and open decisions
- WCAG 2.1 AA. Both themes. Single file, artifact CSP (Google Fonts only, no other external assets).
- Builder must not invent: SMS or WhatsApp sending by the app, a second guardian login, a household entity, cross-academy features.
- **Decided by the owner 2026-09-20:**
  - Second parent: receives notices, and **also invoices if they opt in**. Each family contact gets two switches, "Gets notices" and "Gets invoices (opted in)". Payment links still belong to the primary payer.
  - Coach notes: **visible in the CRM, read-only**, shown on the child drawer and in the Timeline with the coach's name.
  - Students nav item: **retire it** once the People Students view covers it; the old page redirects there. **Superseded 2026-09-22:** the Students label is kept on `/admin/students`, with Staff inside the PEOPLE sidebar group; no redirect. See `engineering-spec.md` §2 and its Reconciliation log.
  - SMS and WhatsApp sent by the app: **yes, planned as a later phase** (provider, parent consent and opt-out, templates, delivery status). Until then the handoff-and-log flow stays. Show "Send from the app (coming)" as a disabled channel option with a one-line explanation, never as working.
- Not a decision, an operational step (show under "How it gets built", not under decisions): new storage for contacts, tags, notes, follow-ups, lead source and logged contact needs database migrations. Production does not run migrations on its own at startup, so each one is run by hand and checked before its feature is switched on.
