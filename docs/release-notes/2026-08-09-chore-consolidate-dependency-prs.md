# consolidate-dependency-prs

PR: #412

## What changed
Consolidates the compatible open Dependabot updates: backend OpenAI, NumPy,
Stripe, tzdata, and Ruff; plus frontend React, React DOM, React/Node types,
ESLint config, and Playwright. The FullCalendar packages move to their matching
latest supported v6 patch release. Transitive frontend packages are pinned to
patched releases so the CI vulnerability gate remains actionable.

## Deploy notes
None. There are no migrations, configuration changes, or manual rollout steps.

## Risk / rollback
The direct updates are patch/minor releases except the Ruff tool upgrade. Ruff
0.16 formatting and lint compatibility changes are included in the same change.
The FullCalendar v7 Dependabot proposal is deliberately excluded because its
stable DayGrid plugin is only available on the incompatible v6 line. Revert
this commit to restore the previous dependency pins if a regression appears.
