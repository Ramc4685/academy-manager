# Skills earned across levels

PR: TBD

## What changed
Parents can see required and optional skills earned at each level, including skills earned ahead of their child’s current placement. New level-up recommendations and automatic approval require at least one configured requirement.

## Deploy notes
No migration or configuration change. Academies using optional-only levels should configure a required skill before recommending promotion. Owners reviewing an already queued recommendation should check the current requirements before manual approval.

## Risk / rollback
Roll back the progress view and completion-rule change together if counts or promotion readiness are incorrect. The progress view reads existing skill records.
