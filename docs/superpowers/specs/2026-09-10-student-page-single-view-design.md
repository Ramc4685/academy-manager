# Student page single view — design

Date: 2026-09-10. Owner decisions from the brainstorming session are recorded inline.
Fourth of four specs from the 2026-09-10 admin-UX session. Depends on spec 2 (families
directory consolidation) for the parent-management move; the layout work itself does not.

## 1. Purpose

`/admin/students/[studentId]` has five tabs: Overview, Training, Sessions, Billing,
Family. Two exist to route around the missing family concept (Billing is mostly a link to
the family page; Family re-shows parent contact fields and a parent picker), and the
student's own fields are split across Overview and Family by an arbitrary form `mode`.
An admin checking "is this kid OK, what are they in, what do they owe, and stop one
class" clicks through three tabs.

Verified: every panel already fetches its own data (`page.tsx` runs three queries; the
panels run their own; tabs mount lazily). The backend composition for this page is spread
across `directory_routes.py`, `progress_routes.py` and `billing_routes.py`, not
`composition/admin.py`. This is a frontend layout change; no new endpoint.

## 2. Owner decisions

| Question | Decision |
|---|---|
| Tabs | Removed. One scrolling page with collapsible sections and a sticky summary rail. |
| Parent data | Off this page. A compact family card links to the family page. `ChangeParentPanel` moves to the family page (spec 2 §6). |
| Sections open by default | Header, Enrollments, Training & attendance. Billing summary line always visible, detail collapsed. Compliance auto-opens only when something is outstanding. |
| Aggregate endpoint | Not built. Panels keep their own queries; skeletons while loading. |

## 3. Layout

Desktop: sticky left rail (≈280px) + one scrolling column. Mobile: rail becomes the top
card, sections stack.

Rail: avatar, name, status chip, level, DOB/age, "Stop all classes" (existing), family
card (parent name, email, phone, login badge → "Open family"), section jump links.

Column, in order:

1. **Enrollments** — the current `SessionsPanel` table with the spec-1 action set, plus
   the per-enrollment billing facts from `BillingEnrollmentsPanel` merged into the same
   rows (fee, discount, autopay chip). One table, not two. Past enrollments stay as the
   second table inside this section, collapsed after five rows.
2. **Training & attendance** — `SkillPathwayPanel`, training snapshot,
   `RecentAttendancePanel`, `EngagementPanel`.
3. **Billing** — one summary line always visible ("$340/mo across 2 classes · nothing
   overdue · autopay on") and a link to the family page; the detail (what the Billing tab
   showed beyond the link) collapsed.
4. **Profile** — `StudentEditForm` as one form: identity fields, DOB, emergency contact,
   medical, notes, t-shirt. The `mode` prop and the split go away.
5. **Compliance** — `ComplianceSummary`; collapsed when clean, open when a waiver or
   medical answer is outstanding.

Section open/closed state is remembered per browser in `localStorage`; deep links
`#enrollments` etc. open and scroll to a section so existing links from the roster and
family pages keep working.

## 4. What leaves this page

`ChangeParentPanel`, parent contact fields in `StudentEditForm mode="family"`, and
`FamilyBillingLink`'s panel body. All reappear on the family page per spec 2. Sequence:
the family page gains "Move child to another family" **before** this page loses the
picker, or admins have no way to reassign a child.

## 5. Out of scope

- Any backend change, aggregate endpoint or read-model work.
- Coach or parent views of a student.
- Redesign of the individual panels' internals (skill pathway, attendance).

## 6. Testing

- e2e `admin-students.spec.ts` rewrites the tab navigation (`getByRole("tab")`,
  `admin-student-training-tab`, `admin-student-compliance-tab`) to section ids; the
  billing route mocks that only the Billing tab installed become part of the page-level
  setup since every section now mounts. `admin-family-billing.spec.ts` and
  `admin-enrollment-withdraw.spec.ts` re-checked for tab assumptions.
- Clean-console spec: no unstubbed 4xx/5xx from the newly always-mounted panels.
- Visual check on phone and desktop for the rail/stack breakpoint.
