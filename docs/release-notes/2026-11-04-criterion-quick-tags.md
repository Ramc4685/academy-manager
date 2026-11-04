# criterion-quick-tags

PR: #1125

## What changed
When a coach adds the optional one-line parent note on a skill they just marked mastered, the skill's criteria now show as tap chips above the note box. Tapping chips writes the note as one sentence ("Nailed it today: thumb is flat on back of handle and elbow in front of body."), so the coach types nothing courtside. A chip shows as pressed when the draft already says that criterion (whole words, any case, and not when it only appears inside a longer criterion). A chip that would push the note past 140 characters is disabled. The coach and admin skill-board endpoints now return each skill's `criteria` list.

## Deploy notes
No migration and no new config. The new `criteria` field is additive on the skill-board responses; deploy backend and frontend together as usual.

## Risk / rollback
Low. The note is still optional and still editable by hand; tapping a chip replaces a hand-typed draft with the templated sentence. Revert this PR to remove the chips and the `criteria` field.
