# skill-ladder-generator

PR: #TBD

## What changed
The program editor (Settings -> Curriculum) gets a "Draft a skill ladder with AI" card when the academy has AI switched on: the owner gives an age band, a level count and optional notes, the model drafts levels, skills and observable criteria for the program's sport, and the owner edits the rows before choosing "Save to program", which writes them through the existing level, skill and criterion routes. New admin routes `GET /admin/ai/status` and `POST /admin/curriculum/programs/{program_id}/ladder-draft`; the draft touches no student, family or enrollment data and every model call lands in `ai_calls` under feature `skill_ladder`, prompt `skill-ladder-v1`, refused up front once the academy's monthly cap is reached.

## Deploy notes
No migration, no new env vars, no manual steps. The feature stays dark until `V2_AI_ENABLED` and `V2_ANTHROPIC_API_KEY` are set: with either unset, `GET /admin/ai/status` answers `{"enabled": false}` so the card never renders, and the draft route answers 503 `Ai.Disabled`.

## Risk / rollback
A bad model answer is a 502 and nothing is saved; a partial "Save to program" (one of the create calls failing) leaves the already-created levels in the program, visible in the normal editor, where the owner can finish by hand. Nothing the model produces is saved or sent on its own. Rollback is a plain revert: no data shape changed, and `ai_calls` rows already written stay valid audit history.
