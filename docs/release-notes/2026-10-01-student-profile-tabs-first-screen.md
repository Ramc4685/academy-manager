# Admin: keep student profile tabs on a phone's first screen

PR: #1049

## What changed

- The "Waiver not signed" warning (#1016) sat between the summary cards and the tabs. On a 390x664 phone (iPhone 14) it pushed the tabs to 734px, below the first screen, breaking #897 and failing the WebKit e2e (#1046).
- The warning now renders directly below the tabs, so it still shows on every tab and the tabs stay on the first screen.

## Deploy notes

- None. Frontend layout only.

## Risk / rollback

- Very low. Same warning, new position. Rollback: revert the PR.
