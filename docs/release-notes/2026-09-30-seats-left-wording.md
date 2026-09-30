# Public page seat chip says "Only N seats left"

PR: #1024

## What changed
- The public class page's low-availability chip now reads "Only N seats left" ("Only 1 seat left"), replacing "N spots left". The fallback without a number reads "A few seats left". This follows the owner's wording choice on 30 Sep.
- The threshold is unchanged: it shows at or below the academy's "only N seats left" setting (default 3; 0 hides it).

## Deploy notes
Frontend-only text change. No migration and no backend change.

## Risk / rollback
Copy only. Revert the PR to restore the old wording.
