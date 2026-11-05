# `ai` context: model port, prompt versions and the `ai_calls` audit

Phase 1 of `docs/plans/2026-11-04-ai-strategy.md` (section 4, "AI
foundation"): plumbing only. **No feature calls the model yet, and no parent
or child data goes to any model.** This README is the contract; the tests in
`backend/v2/tests/unit/test_ai_foundation.py` and
`backend/v2/tests/contract/test_ai_calls_real_mongo.py` decide.

## Layout

| File | What it is |
|---|---|
| `domain/models.py` | `DEFAULT_MODEL` (`claude-sonnet-5-5`, a constant, not a setting), `LlmResult`, `AiCallRecord` |
| `domain/prompts.py` | `PROMPTS`: feature -> `PromptVersion(version, system_text)`; one unused placeholder |
| `domain/errors.py` | `AiDisabled` (503), `AiMonthlyCapReached` (429), `AiProviderError` (502) |
| `application/ports.py` | `LlmPort`, `AiCallRepository`, `MonthlyCapSource` |
| `application/use_cases/record_ai_call.py` | `RecordAiCall`: `assert_under_cap()` refuses before the call; `execute()` always writes one row |
| `infrastructure/anthropic_llm_port.py` | the one `LlmPort` adapter: Anthropic Messages API over plain `httpx`, no SDK |
| `infrastructure/disabled_llm_port.py` | wired whenever AI is off; every call raises `AiDisabled` |
| `infrastructure/mongo_ai_call_repo.py` | `MongoAiCallRepository(TenantScopedRepository)`, collection `ai_calls` |
| `backend/v2/migrations/0220_ai_calls.py` | `(academy_id, created_at)` and `(academy_id, feature, created_at)` indexes |
| `backend/v2/composition/ai.py` | `compose_ai(db, settings)`: the gate and the cap lookup; attached at `app.state.ai` |

## Gating

`V2_AI_ENABLED` (default `False`) and `V2_ANTHROPIC_API_KEY` (default unset)
in `shared/config/settings.py`. The real adapter is constructed only in
`composition/ai.py::compose_ai` and only when both are set; otherwise
`DisabledLlmPort`. `tests/structural/test_email_sender_construction.py`
fails on any other construction site, exactly as it does for Resend.

## The audit row

Collection `ai_calls`, one document per model call.

| Field | Meaning |
|---|---|
| `academy_id` | stamped by the repository from the tenant scope |
| `feature` | the calling feature's key in `PROMPTS` |
| `prompt_version` | `PromptVersion.version` that produced the call |
| `model`, `input_tokens`, `output_tokens`, `cost_cents` | from `LlmResult`; cost is list price rounded up to a whole cent |
| `approver` | user id of the human who approved the output, or `null` |
| `created_at` | UTC |

## The cap

`ai.monthly_call_cap` on the academy document (`academies`), read by
`composition/ai.py::AcademyAiCapLookup`; absent or invalid means
`DEFAULT_MONTHLY_CALL_CAP` (200). `RecordAiCall.assert_under_cap()` counts the
academy's rows since the first of the current UTC month and raises
`AiMonthlyCapReached` when one more would exceed the cap; every feature calls it
before `llm.complete`. `execute()` only writes the audit row, even past the cap,
so a spent call is always counted. There is no write path for the cap yet;
it is set by hand until a Growth-tier screen exists.

## Entitlement

Whether an academy may use AI at all is `has_feature(academy_id, "ai")` in
`contexts/platform/billing` (see that context's README). This context does
not read plans.

## B5: month-close narrator (paid, owner-only)

Feature key `month_close_narrator`, prompt `month-close-narrator-v1`, use case
`application/use_cases/narrate_month_close.py`, route
`POST /api/v2/admin/reports/month-close/narrative?period=YYYY-MM`
(`interfaces/admin/ai_reports_routes.py`, wired in `composition/ai_reports.py`
at `app.state.ai_reports`). Order: `AiEntitlement.has_ai()` (403
`Ai.NotEntitled`) -> `RecordAiCall.assert_under_cap()` (429) -> `complete`
-> `RecordAiCall.execute` -> parse -> number and link check (502).

What the model sees: `reduce_month_close_payload` over the owner's existing
month-close view and nothing else: period, timezone, the money section's cents
and rate, invoice counts, autopay run counts and state, the four odd checks
with at most five `{label, href}` items each, and the warning codes. No ids,
void reasons, discounts, dates, emails or phones.

Never computes money: every number token in the answer must be a cents value
from the input (as cents or dollars), a count or rate as given, or the
period's digits; every `fix_first` href must be an odd item's href or one of
`/admin/payments`, `/admin/dues`, `/admin/families`, `/admin/billing-health`,
`/admin/reports`. Anything else is a 502 after the call is recorded.

Where the human is: the owner clicks "Explain this month" on the Reports page
and reads the result there; the owner is the `approver` on the `ai_calls` row.
Nothing is stored and nothing reaches a parent.
