# winback-wording-technique-observations

PR: #TBD

## What changed
Two paid AI features for academies whose plan includes "ai". Win-back emails (30/60/90 days after a child leaves) can get an AI-written second paragraph that uses the child's first name, current level and up to three recent passed skills; the owner turns this on with a new Settings -> Notifications checkbox, "Personalise win-back emails with AI". Coaches get a "Draft from what I saw" box in the skill-notes panel: they type what they observed (text only, no audio or video), the model maps it to one criterion of the child's current level and suggests a parent-friendly sentence, and the coach edits and saves it as an ordinary skill note.

## Deploy notes
No migration, no new collection or index. The feature stays dark until `V2_AI_ENABLED` and `V2_ANTHROPIC_API_KEY` are set and the academy's platform plan has the "ai" feature; until then the win-back email keeps its templated wording and the coach's AI box stays hidden (and would answer 503 "Ai.Disabled" if called). The win-back switch is a standing approval by the owner, not per-message review: once `ai.win_back_personalised` is on (owner-only routes `GET/PUT /api/v2/admin/ai/win-back-personalised`, the owner's user id is stored in `ai.win_back_personalised_by` and recorded as the approver of every drafted paragraph), the daily job sends the AI paragraph without anyone reading it first. The technique draft stores nothing but the `ai_calls` row; the saved skill note is the human approval.

## Risk / rollback
If the model misbehaves, the worst case for win-back is one odd paragraph in an automated email; the first and third paragraphs and the subject never change, the paragraph must name the child and may contain no digits other than the milestone, and any AI error (disabled, not entitled, cap, provider, unreadable answer) falls back to the template and still sends. Roll back by having the owner untick the checkbox (one PUT, takes effect on the next daily tick) or by unsetting `V2_AI_ENABLED`. The technique draft never reaches a parent on its own; a bad suggestion is simply not saved. Reverting the PR removes both routes and leaves the `ai.win_back_personalised*` fields inert on the academy document.
