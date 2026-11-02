# certificate-level-band

PR: #1109

## What changed
The printable level certificate has a cleaner, bolder layout: white paper on the left with the academy logo, "Certificate of achievement", the student's name on a volt marker stroke, the level, a checklist of skills mastered and the date and "Awarded by" lines; on the right, a full-height band in the level's own curriculum colour (the colours set under Curriculum, belt-style by default) with a large level number and "of N", and one shuttle feather per level in the program, each in its level colour: earned levels filled, this level outlined, levels still to come hollow. The heavy double frame, corner feathers, pill ribbon and round seal are gone. The student's name is measured and shrunk to fit on one line, and more than eight skills flow into three columns. Same content, same one-page Letter-landscape print.

## Deploy notes
None. No migration. `GET .../certificates/{certId}` (parent and admin) gains a `levels` list (name and colour of every level in the program); older clients ignore it.

## Risk / rollback
Visual only. Roll back this PR to restore the previous certificate design.
