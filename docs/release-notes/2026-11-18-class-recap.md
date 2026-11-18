# Class recaps

PR: TBD

## What changed
Coaches and owners can record the lesson and each child's practice on a dated class. The after-class report can go to the owner or, when enabled, use AI to add confirmed details. Parents see their own child's practice and current pass status under Progress.

## Deploy notes
Migration `0243_class_recaps_indexes` adds indexes for recaps and private handoffs. Check for the migration in the production dry-run and a successful release command. The collections start empty and need no backfill.

## Risk / rollback
Incorrect attendance or report interpretation can affect a child's practice record. The owner can correct the recap in the class screen. Revert the change to remove the feature. The collections can stay in place.
