# BLNO's slug becomes blno-academy, the host its families use

PR: #1000

## What changed

- Migration `0207_blno_slug_blno_academy` renames the production BLNO academy slug from `blno-badminton` to `blno-academy`.
- Invoice, add-card and Stripe return links now point at `https://blno-academy.courtmastr.com`, the address BLNO's families already use and the one in CORS.
- A verified `academy_domains` row keeps `blno-badminton.courtmastr.com` mapped to BLNO, so links already sent keep working after the multi-academy switch.

## Deploy notes

- The migration runs in the Fly release_command on the next deploy.
- It is idempotent, and it skips if another academy holds the slug.
- No env or secret change is needed.
- When multi-academy is switched on, use platform base domain `courtmastr.com`.

## Risk / rollback

- Low. In single-academy mode every host still serves BLNO; only the host in generated links changes.
- Rollback: set the slug back with `db.academies.updateOne({academy_id:"acad_blno_badminton"},{$set:{slug:"blno-badminton"}})`. The added `academy_domains` rows are harmless to leave.
