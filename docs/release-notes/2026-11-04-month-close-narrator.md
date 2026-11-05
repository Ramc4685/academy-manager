# month-close-narrator

PR: #TBD

## What changed
Owners on a plan with the `ai` feature get an "Explain this month" button on the Reports page's month-close view. It asks the model for a short summary of the month and up to three "fix first" links, built only from the numbers already on the page; every number and link in the answer is checked against the month-close view before it is shown.

## Deploy notes
No migration, no new collection. The feature stays dark until `V2_AI_ENABLED` and `V2_ANTHROPIC_API_KEY` are set on the API and the academy's platform plan has the `ai` feature; without those the button is hidden or the page shows a plain sentence (503 / 403). Each click writes one `ai_calls` row with the owner as approver and counts against the academy's monthly cap.

## Risk / rollback
If the check is wrong the owner sees a 502 sentence, never a wrong figure: an answer with a number or link not in the view is refused. Nothing is stored, no parent is contacted, no money moves. Roll back by reverting the PR or unsetting `V2_AI_ENABLED`; the rest of the Reports page is unchanged.
