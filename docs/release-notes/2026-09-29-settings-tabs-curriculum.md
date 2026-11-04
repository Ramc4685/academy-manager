# Settings tabs renamed, Curriculum tab, Progress sidebar (Settings overhaul Phase 3 PR 11)

PR: #1008

## What changed

- **Gateway tab is now Integrations** (`?panel=integrations`). It keeps the Stripe Connect card and the platform fallback card, and gains a read-only **Email** section: mail goes out through CourtMastr's mail service under the academy's name. It shows the sender name and reply-to already stored on the academy (edited in Academy profile) and says using your own email account is coming later. Still owner-only, as Gateway was.
- **Notify tab is now Notifications** (`?panel=notifications`). The "Daily admin digest" switch is relabelled "CC admins on coach digests" with helper text. The stored field (`daily_digest_to_admin`) and behaviour are unchanged: it copies admins on each coach's daily digest email.
- **New Curriculum tab** (`?panel=curriculum`). The Pathway authoring UI moved as-is: program list, create program, "Seed badminton pathway" (still gated on the academy's sport), the program editor (levels, skills, references) and lesson cards. The editor opens inside the tab via `?panel=curriculum&program=<id>`. Components live in `frontend/components/admin/curriculum/`. No API change (`/admin/curriculum/programs`).
- **Sidebar "Pathway" is now "Progress"** and points at `/admin/pathway/progress`. `/admin/pathway` redirects to `?panel=curriculum`; `/admin/pathway/[programId]` redirects to `?panel=curriculum&program=<id>`. Progress routes are unchanged.
- **Old links keep working:** `?panel=gateway` maps to Integrations and `?panel=notify` to Notifications. The page keeps the other query params, so Stripe's return links (`?panel=gateway&stripe=connected|error|refresh`) still show their banner. The backend still emits `panel=gateway` for those links.
- **Setup checklist links fixed:** Card payments links to Integrations; Branding links to Academy profile (its old `branding` key was already a redirect).
- Tab order: Academy profile, Billing rules, Integrations, Notifications, Family policies, Session types, Public page, Curriculum. Session types is removed by the next lane.

## Deploy notes

- No migration, no backend behaviour change beyond two checklist hrefs. BLNO behaves as before.
- The Progress sidebar item lands on the progress overview, which renders "Progress overview is not enabled" unless `NEXT_PUBLIC_SKILL_PROGRESS_OVERVIEW=1` is set at build time. It is not set in any deploy config in this repo.

## Risk / rollback

- Main risk: an external bookmark or e2e using the old tab labels ("Gateway", "Notify"). Panel keys still resolve; only visible labels changed.
- Rollback: revert this PR. No data changes.
