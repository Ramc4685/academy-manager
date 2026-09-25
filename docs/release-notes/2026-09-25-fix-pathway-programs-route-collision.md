# Skill Pathway programs load and save again

PR: #967

## What changed

- Skill Pathway program list and create moved to `GET/POST /api/v2/admin/curriculum/programs`. Since #934, the public page's programs also used `GET/POST /api/v2/admin/programs`, and the public page handlers answered both. Admins saw public page programs on the Pathway page, every card showed "Inactive", "View Pathway" said "Could not load pathway", and "Create Program" always failed. The progress overview, the student progress page (program picker and Place in level), and the student profile's training snapshot showed the same wrong list. They all now read skill programs. The public page's programs panel keeps `/api/v2/admin/programs` and does not change.
- "+ Add Skill" on a pathway level works. The form now sends the level's `program_id` and the next `sequence`, and it offers only the scoring types the backend accepts. An unknown scoring type now returns 422 instead of a server error.
- A new backend test builds the full app and fails if any method and path pair is registered twice.

## Deploy notes

- No migration and no data changes. Deploy the backend and frontend together: a frontend that still calls `/admin/programs` for skill programs keeps getting public page programs until the new frontend is live.
- Coach, parent, student, digest, and Inbox level-up surfaces are unchanged. They never called these routes.

## Risk / rollback

- Low risk. The change moves two admin-only routes and fixes one admin form payload.
- Known limit: coach, digest, and student surfaces support only one active skill program per academy. Now that "Create Program" works, creating a second active program can break those surfaces. That fix is not in this PR.
- Rollback: revert this PR. Nothing is stored differently.
