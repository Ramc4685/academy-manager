# ios-input-zoom

PR: #1115

## What changed
On phones and tablets, text boxes, dropdowns and text areas now use at least 16px text. iPhones zoom into any smaller field when it is tapped and stay zoomed after the next page loads, so pages looked cut off on the left in Safari and in the iOS app. Desktop browsers keep the existing compact sizes (the rule only applies to touch screens).

## Deploy notes
CSS only (`frontend/app/globals.css`); ships with a normal frontend deploy, no app rebuild needed.

## Risk / rollback
Form fields on touch screens get slightly larger text, which can make a tight field look crowded. Revert the rule in `globals.css` to undo.
