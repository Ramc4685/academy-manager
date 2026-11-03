# Implementation Plan: Waiver signing upgrade

Date: 2026-11-02. Baseline: `origin/main` at `ff757137d`. Status: draft, awaiting owner review.

## Overview

The owner has a new participation agreement (risk acknowledgment, liability release, medical
authorization) drafted for Illinois attorney review. It is a form, not a block of text: academy
details, parent-entered fields, initials on key sections, separate adult and minor release
sections, and a fixed term. Today's waiver system stores one plain-text body per version and
records a one-click acceptance. This plan makes every signature defensible first, then teaches
templates to carry the new agreement, then closes the operational loop for staff.

## Current behavior (on main)

- **Templates.** Several live waivers at once, each a lineage of immutable versions with a sha256
  `content_hash`. Each is assigned to nobody, all families, or chosen programs
  (Settings > Family policies > Waivers, #1016/#1023). The body is one plain-text field.
- **Registration.** Waiver step shows the body and an **I Accept** / **I accept all** button. No
  typed name, no consent statement, no IP or browser captured. `WaiverAcceptance` stores version,
  hash, time, template id, lineage. On approval it becomes a `WaiverSignature` per student with
  the signer name copied from the parent profile.
- **Existing families.** `/parent/waivers` lists each required waiver; name field is optional and
  falls back to the email; one button signs every pending waiver for every active child.
  IP comes from `request.client.host` (`backend/v2/interfaces/parent/waiver_routes.py:38`), which
  behind Fly is the proxy address, not the parent's. The body renders without
  `whitespace-pre-wrap` (`frontend/app/(parent)/parent/waivers/page.tsx:171`), so line breaks collapse.
- **Signed copy.** `WaiverSignature.artifact_id` exists but nothing writes it. No email receipt, no
  parent download. Admins can view a signature at `/admin/waivers/signatures/[id]`.
- **Staff.** Owner decision 9: warn, never block. Registration queue shows an UNSIGNED chip, the
  admin student page lists per-waiver status. Coaches see nothing.
- **Profile data already held.** Student: `date_of_birth`, `emergency_contact_name`,
  `emergency_contact_phone`, `medical_notes`. Academy: `name`, `address`. No legal entity name,
  insurance, pickup list, alternate contact.
- **No PDF library** in backend or frontend. The level certificate prints via print CSS; reuse
  that pattern for the signed copy.

## Architecture decisions

1. **Signed copy is a printable page plus an email, not a stored PDF.** The template version is
   immutable and hash-pinned and the signature row holds everything else, so a deterministic
   render is as trustworthy as a stored file and needs no Firebase Storage setup. Browser
   "Save as PDF" gives a file. `artifact_id` stays unused; delete it if nothing needs it by the
   end of Phase 2.
2. **Templates become a list of sections**, not a markup language. Each section has a heading,
   body, `initials_required`, and `audience` (`all` | `adult` | `minor`). A legacy plain body
   reads as one `all` section, and its hash stays the hash of the body text, so no existing
   signature turns "outdated".
3. **Academy details resolve at publish time.** Placeholders such as `{{academy.legal_name}}` are
   substituted when a version is published, and the hash covers the resolved text, so parents
   sign exactly what they saw. Publish refuses a template with an unfilled placeholder.
4. **Answers are snapshotted on the signature.** Emergency, medical, insurance and pickup answers
   are stored on the signature as attested, and the fields the student profile already owns are
   written back to it. One place to read "what did they declare when they signed".
5. **Sensitive answers are owner/admin only.** Coaches get a boolean "has medical note" flag and
   the waiver status, never the text. Wrong persona keeps returning 404.
6. **Still warn, never block** (decision 9). New statuses (`expired`) surface the same way as
   `pending` / `outdated`.

## Task list

Sizes: XS 1 file, S 1-2, M 3-5, L 5+ (split anything larger). Every task ships with a release
note in `docs/release-notes/` and focused tests; migrations are applied by hand in prod.

### Phase 1: Defensible signatures (no template changes)

**Task 1.1: Waiver body keeps its line breaks on the parent page** (XS)
- [ ] Parent waivers page renders the body with `whitespace-pre-wrap`, matching registration.
- Verify: vitest snapshot or e2e assertion on a multi-line body.
- Files: `frontend/app/(parent)/parent/waivers/page.tsx`.

**Task 1.2: Record the parent's real IP** (S)
- [ ] Extract the client-IP resolver from `payment_routes.py:175` into `backend/v2/shared/http/`
  and use it in payment routes and the waiver accept route.
- [ ] Test: `x-forwarded-for` / `fly-client-ip` headers produce the client address on a signature.
- Files: `backend/v2/interfaces/parent/payment_routes.py`, `.../parent/waiver_routes.py`, new
  shared helper, interface test.

**Task 1.3: Explicit signing on the parent waivers page** (M)
- [ ] Shared `WaiverSignBlock` component: required full legal name, an unticked consent checkbox
  ("I agree to sign electronically and that my typed name is my signature"), one checkbox per child
  (all ticked by default), **Sign** button enabled only when all are complete.
- [ ] Backend `AcceptParentWaiver` requires a non-blank `signer_name` (no email fallback),
  `consent=true`, and an optional `student_ids` subset limited to the parent's own children
  (anything else is 404). Signature stores `consent_text` version.
- [ ] Interface + application tests; e2e `saas-parent-waivers.spec.ts` updated.
- Files: `parent_student_waivers.py`, `domain/models.py`, `interfaces/parent/waiver_routes.py`,
  `frontend/components/parent/waiver-sign-block.tsx`, parent waivers page.

**Task 1.4: Same signing step at registration** (M)
- [ ] Registration waiver step uses `WaiverSignBlock` (children list is the one child being
  registered).
- [ ] `WaiverAcceptance` gains `signer_name`, `consent_text`, `ip_address`, `user_agent`; approval
  copies them into the `WaiverSignature` instead of reading the parent profile.
- [ ] Old applications without the new fields still approve (fields are optional; warn only).
- Files: `manage_application.py`, `domain/models.py`, `admin_registration_review.py`,
  `interfaces/parent/onboarding_routes.py`, onboarding page, tests.

**Task 1.5: Printable signed copy for parents and admins** (M)
- [ ] `GET /api/v2/parent/waivers/signatures/{id}` returns the exact version's text, signer,
  children, time (academy timezone), IP, browser, hash, signature id; 404 unless it is the
  caller's own.
- [ ] `/parent/waivers/signatures/[id]` page with print CSS; "Download / print" link from each
  signed row. Admin signature page gets the same print layout.
- Files: parent waiver routes + use case, new parent page, admin signature page, tests, route
  manifest (new frontend route checklist: manifest + 2 route counts).

**Task 1.6: Email receipt on signing** (S)
- [ ] One email per signing action through the existing communications/Resend path, listing each
  waiver and child signed, the audit block, and a link to the signed copy. Sent once even on retry.
- Files: communications use case + template, call site in accept and approval paths, tests.

**Checkpoint: Phase 1**
- [ ] Backend tests, frontend vitest, parent waiver e2e green.
- [ ] Sign on staging as a parent: real IP recorded, receipt arrives, printable copy matches.
- [ ] Owner review before Phase 2.

### Phase 2: Templates that carry the new agreement

**Task 2.1: Sectioned templates, backend and rendering** (M)
- [ ] `WaiverTemplate.sections` (heading, body, initials_required, audience); legacy body reads as
  one section and keeps its existing hash; new versions hash canonical JSON of sections.
- [ ] Parent page, registration step and signed copy render headings and sections.
- [ ] Contract test: an existing signed legacy template still reads "signed".
- Files: `domain/models.py`, `admin_waiver_templates.py`, Mongo template repo, render component,
  tests.

**Task 2.2: Section editor in Settings** (M)
- [ ] Draft editor adds, edits, reorders and deletes sections, toggles initials and audience;
  preview shows the parent view.
- Files: `frontend/components/admin/waivers/waivers-management.tsx` (split out a section editor),
  admin routes payload, tests.

**Task 2.3: Academy placeholders resolved at publish** (S)
- [ ] Academy profile gains `legal_name`, `facility_name`, `facility_address`, `released_parties`
  (Settings > Academy profile).
- [ ] Publish substitutes `{{academy.*}}` placeholders and refuses unknown or empty ones with a
  message naming them.
- Files: identity academy use cases + settings tab, `admin_waiver_templates.py`, tests.

**Task 2.4: Initials on marked sections** (S)
- [ ] Each `initials_required` section shows an initials box; Sign stays disabled until all are
  filled; signature stores `initials: {section_id: "RV"}`; signed copy shows them.
- Files: sign block, accept use cases, models, tests.

**Task 2.5: Participant information block, backend** (M)
- [ ] Template flags which blocks it collects: `emergency`, `medical`, `insurance`, `pickup`.
- [ ] New student fields: alternate contact name/phone, relationship, emergency care
  instructions, insurer, policyholder, coverage confirmed date, authorized pickup list,
  independent departure (yes/no). Never a policy number.
- [ ] Accept validates required answers (the insurance block is fully required when a template
  turns it on, decision D), snapshots them on the signature, writes back profile fields.
- Files: enrollment student model + repo, onboarding models + accept use cases, migration if an
  index is needed, tests.

**Task 2.6: Participant information block, parent UI** (M)
- [ ] Sign flow shows the collected blocks per child, prefilled from the profile, editable,
  with required markers. Registration step does the same for the new child.
- Files: sign block, parent waivers page, onboarding page, api client, vitest + e2e.

**Task 2.7: Who can see the answers** (S)
- [ ] Admin signature page and student page show answers to owner and admin only; coach
  endpoints expose only `has_medical_note` and waiver status. Security test for each persona.
- Files: admin waiver routes/views, coach student view, `docs/security-matrix.md` if a new row.

**Task 2.8: Term and expiry as a waiver setting** (S, decision B)
- [ ] Each waiver's Assign panel in Settings picks never / `valid_until` date /
  `renew_every_months`; status adds `expired`; parent home nudges 14 days ahead; admin report
  counts expired. BLNO set to 12 months at rollout.
- Files: `parent_student_waivers.py`, `student_waiver_status.py`, admin report, parent-home lib,
  tests.

**Task 2.9: Adult and minor paths by date of birth** (M, decisions C and E)
- [ ] Age on signing day (academy timezone) from the student's date of birth picks `adult`
  (18+) or `minor` sections; a missing date of birth blocks signing with a prompt to add it.
- [ ] Adult path: the typed name must be the participant's own and the consent line reads
  "I am the participant". Signing still happens from the logged-in account; record which
  path was used on the signature.
- [ ] A participant who turns 18 while their minor-path signature is current shows "re-sign as
  adult" (status `outdated`).
- [ ] No child acknowledgment (decision E).

**Checkpoint: Phase 2**
- [ ] The attorney-reviewed agreement entered as sections on staging, published, signed end to
  end as a parent with two children; signed copy reads like the paper form.
- [ ] Existing BLNO signatures unchanged ("signed" before and after deploy).

### Phase 3: Staff loop

**Task 3.1: Coach roster and check-in flag** (S)
- [ ] Coach roster and attendance rows show "Waiver missing / expired" and a "Medical note" chip.
  Warning only.

**Task 3.2: Reminders** (S)
- [ ] Parent daily digest includes pending, outdated and soon-expiring waivers; one announcement
  email when a new required version is published.

**Task 3.3: Compliance export** (XS)
- [ ] Admin waiver report gets a CSV download per waiver (student, status, version, signed at,
  signer), no medical or insurance answers.

**Task 3.4: Rollout runbook for BLNO's new agreement** (XS, docs)
- [ ] Steps: fill academy profile fields, publish as a new version of the existing lineage (every
  family becomes "outdated"), send the announcement, watch the report. Notes for the prod
  migrations each phase needs.

**Deferred:** front-desk tablet signing for walk-ins and trials. Revisit if trials need it; a
signing link emailed to the parent covers most of it.

**Checkpoint: Complete**
- [ ] All acceptance criteria met, release notes in place, owner signs off.

## Parallel work

Tasks 1.1, 1.2 and 1.5 are independent. 1.4 and 1.6 need 1.3. In Phase 2, 2.1 comes first;
2.3 and 2.5 can then run in parallel; 2.2, 2.4, 2.6 follow 2.1; 2.7 follows 2.5. Phase 3 needs
only Phase 1 plus 2.8 for the expired status.

## Risks and mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Agreement text not attorney-reviewed | High | Publishing the new agreement (3.4) is gated on the owner confirming review. Software makes no legal claims. |
| Moving to sections changes legacy hashes and marks every family "outdated" | High | Legacy hash rule kept; contract test on real-shaped BLNO data (2.1). |
| Medical/insurance answers leak to wrong persona or tenant | High | Tenant-scoped reads, persona 404s, explicit security tests (2.7). |
| Mass re-sign after rollout annoys families | Medium | One clear announcement email, receipt, and a phone-friendly sign flow; stagger rollout. |
| Prod migrations applied by hand out of order | Medium | Every migration additive and idempotent; deploy notes per PR. |
| Receipt email lands in spam | Low | Signed copy stays available in the app regardless. |

## Owner decisions (2026-11-02)

- **A. Signature style: typed name only.** Full legal name plus the e-signature consent checkbox;
  no drawn signature (cheapest, legally sufficient).
- **B. Term: a setting per waiver.** In Settings > Family policies each waiver picks "never
  expires", a fixed end date, or "renew every N months". BLNO starts at 12 months.
- **C. Adult or minor: decided by date of birth.** On signing day, a participant aged 18 or older
  gets the adult sections (Section 7) and signs as themselves; under 18 gets the
  parent/guardian sections (Section 8). A student with no date of birth must have one entered
  before signing.
- **D. Insurance: required, as drafted.** The insurance block is required when a template turns
  it on: confirm active coverage, insurer, policyholder, confirmation date. Still no policy
  numbers.
- **E. Age cutoff 18.** Read as the adult/minor cutoff. No separate child acknowledgment is
  built (the draft's "minor signature, when age appropriate" line is dropped from the online
  form); add it later if the attorney wants it.
