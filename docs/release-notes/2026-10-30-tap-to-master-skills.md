# tap-to-master-skills

PR: #1097

## What changed
Coaches mark progress from the session Skills tab's new "Got it" mode: pick today's skill, tap each student who got it. The last skill of a level queues the move up, and a new evening job (18:30 academy time) moves the student up and issues the certificate unless the tap is undone first. Levels marked "requires admin approval" still wait for the owner.

## Deploy notes
No migration. New scheduled job `auto_approve_level_ups` registers on boot. Before deploying, the owner should review the level-up queue: rows already pending there are auto-approved at the first evening run unless their level requires approval.

## Risk / rollback
A wrong auto-approval advances a student and issues a certificate, the same as an owner approval. To stop it, set `requires_admin_approval` on the levels, or revert this PR. Coach taps and undos are ordinary skill-progress writes.
