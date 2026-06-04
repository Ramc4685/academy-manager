# student profile redesign options

## Current State

Status: active

## Problem

Explore current student profile data and propose UI redesign options without implementation

## Changed Files

- None recorded yet.

## Log

- 2026-06-04T17:02:52 main/NA: Task ledger created.
- 2026-06-04T17:04:36 main/working: Read project docs, frontend rules, admin ticket sheet, student profile page, admin student API DTOs, Mongo student repository, E2E coverage, and local seed fields. Found current page exposes profile edit, sessions, payment, engagement, payment history, and parent reassignment, while seed data also contains emergency contact, medical notes, skill_level, waiver data, previous experience, move log, and attendance.
- 2026-06-04T17:11:58 main/working: Started visual companion at http://localhost:57738 and added first student profile direction comparison screen with three options: operations command center, coaching progress profile, and family/billing control.
- 2026-06-04T17:12:24 main/working: User asked which data should be included in the student UI; preparing recommended data inventory and priority grouping from current BFF plus seed data gaps.
- 2026-06-04T17:14:55 main/working: Refined direction after user clarified the target user is academy admins managing students. Added visual companion screen comparing admin dashboard profile, tabbed student record, and timeline-led record; recommended dashboard profile.
- 2026-06-04T17:20:39 main/working: User selected B: Tabbed Student Record. Proceeding with design section approval around tabbed IA with compact always-visible status summary.
- 2026-06-04T17:24:26 main/working: User approved tabbed student record information architecture and asked about editability. Next design section will define editable fields, guarded actions, and data additions.
- 2026-06-04T17:30:17 main/working: User approved editability mockup and asked for detailed contents of the remaining tabs. Defining tab-by-tab data inventory and edit/read-only behavior.
- 2026-06-04T17:35:23 main/working: Wrote student profile redesign spec and self-reviewed it. Tightened ambiguous BFF additions: level normalization, waiver field types, recent attendance limit, age derivation, and move history first-implementation scope.
## Verification

- No verification recorded yet.
- 2026-06-04T17:36:24: Design-only verification: spec self-review completed; placeholder/ambiguity scan found no unresolved TBD/TODO/FIXME/Open Decision markers. No app tests run because no application code was changed.
## Reusable Lessons

- None recorded yet.
