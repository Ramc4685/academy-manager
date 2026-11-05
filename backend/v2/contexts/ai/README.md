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
| `application/use_cases/record_ai_call.py` | `RecordAiCall`: counts this UTC month's rows, refuses past the cap, writes one row |
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
`DEFAULT_MONTHLY_CALL_CAP` (200). `RecordAiCall` counts the academy's rows
since the first of the current UTC month and raises `AiMonthlyCapReached`
when one more would exceed the cap. There is no write path for the cap yet;
it is set by hand until a Growth-tier screen exists.

## Features

### `skill_ladder` (B1, prompt `skill-ladder-v1`)

`application/use_cases/draft_skill_ladder.py::DraftSkillLadder`, wired by
`composition/ai_curriculum.py` at `app.state.ai_curriculum`, behind
`POST /admin/curriculum/programs/{program_id}/ladder-draft`
(`interfaces/admin/ai_curriculum_routes.py`, admin persona). The model sees
exactly `SkillLadderInput`: `sport` (from the program, through
`ProgramSportLookup` in composition because this context never imports
curriculum), `age_band`, `level_count` and the owner's `notes`, serialised as
one JSON object; no student, family or enrollment data. The use case calls
`RecordAiCall.assert_under_cap()` before spending tokens, records the row
before parsing, and reads the answer strictly (`parse_skill_ladder`: optional
```` ```json ```` fence, pydantic shape, exactly `level_count` levels numbered
1..n, 2-6 skills each, 1-5 criteria each, scoring type from the curriculum
literal), so a bad answer is 502 `Ai.ProviderError` and nothing half-saved.
The human approves in the program editor's draft card
(`frontend/components/admin/curriculum/skill-ladder-draft-card.tsx`): the
draft is editable local state until "Save to program" walks it through the
existing create level / skill / criterion routes. `GET /admin/ai/status`
(`{enabled}`) hides the card while the disabled port is wired.

## Entitlement

Whether an academy may use AI at all is `has_feature(academy_id, "ai")` in
`contexts/platform/billing` (see that context's README). This context does
not read plans.
