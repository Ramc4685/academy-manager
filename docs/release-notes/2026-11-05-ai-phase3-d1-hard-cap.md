# AI Phase 3 D1: hard AI cap

## What changed

- The monthly AI call cap is now a hard ceiling. Each model call reserves a slot on a per-academy, per-UTC-month counter (`ai_call_counters`) with one atomic update, so concurrent calls at the cap minus one let exactly one through. Before, the check counted `ai_calls` rows and then inserted, so a burst at the cap could overshoot it.
- A failed model call (provider error, or a failure while preparing it) gives its slot back instead of burning it. Every existing AI feature uses the reservation: skill ladder, roster import mapping, pipeline reply, progress narrative, month-close narrator, win-back note and technique observation.
- New optional per-feature daily ceiling read from `ai.daily_call_cap.<feature>` on the academy document. When it is absent there is no daily ceiling. A call over it answers 429 `Ai.DailyCapReached`, the same error shape as the monthly 429 `Ai.MonthlyCapReached`.
- Unchanged: the default monthly cap of 200, the A3 usage meter (`GET /admin/ai/usage`, still counted from `ai_calls`), and the `ai_calls` audit row written for every spent call.

## Deploy notes

- Apply migration 0226 (`0226_ai_call_counters`) in production before deploying. It creates the unique `(academy_id, key)` index on the new, empty `ai_call_counters` collection; without it the cap still fails closed, but two racing first-of-the-month calls could create a second counter document.
- Counters start at zero on deploy and are not seeded from `ai_calls`, so an academy that already made calls this month gets up to its full cap again for the rest of the month. AI features are still gated by `V2_AI_ENABLED`, `V2_ANTHROPIC_API_KEY` and the plan's `ai` feature.
- No daily ceiling is set anywhere by this change. To set one for an academy, set `ai.daily_call_cap.<feature>` on its `academies` document by hand (the plan proposes 50 a day for "ask the academy").

## Risk / rollback

- If wrong, an academy could be refused AI calls below its cap (a counter that drifts up) or pass it (a counter that drifts down). A slot is released only when the block raises, and never below zero. Rolling back the PR restores the count-then-insert check; the `ai_call_counters` collection and migration 0226 are harmless left in place.

PR: TBD
