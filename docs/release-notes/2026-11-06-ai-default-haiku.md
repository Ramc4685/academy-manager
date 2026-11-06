# AI features run on Claude Haiku 5.5

## What changed

- Every AI draft (pipeline reply, progress narrative, win-back note, technique observation, skill ladder, import column mapping, month-close narrative) now calls `claude-haiku-5-5` instead of `claude-sonnet-5-5`. Haiku 5.5 lists at $0.10 / $0.50 per million input / output tokens for prompts under 100K tokens, against $2 / $10 for Sonnet 5.5, so each draft costs about 20 times less. It is still a paid API tier, so the no-training promise to parents is unchanged.
- The `ai_calls` cost audit prices Haiku calls at the Haiku rate. Calls still round up to a whole cent each, so the audit overstates real spend at this price; the monthly cap counts calls, not cents, and is unaffected.
- The Sonnet price row stays, so a single feature can be moved back to Sonnet later if Haiku's wording falls short.

## Deploy notes

- None. Same `V2_ANTHROPIC_API_KEY`, no migration, no new setting.

## Risk / rollback

- Draft wording may be plainer than Sonnet's. Every draft is still reviewed by staff or a coach before anyone sees it. Rollback: set `DEFAULT_MODEL` back to `claude-sonnet-5-5`.

PR: #1157
