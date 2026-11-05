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

## Entitlement

Whether an academy may use AI at all is `has_feature(academy_id, "ai")` in
`contexts/platform/billing` (see that context's README). This context does
not read plans.

## B6: win-back wording and text-only technique observations (paid)

Two features behind `AiEntitlement.has_ai()` (`has_feature(academy, "ai")`),
each in order: entitlement (403 `Ai.NotEntitled`) -> `assert_under_cap` (429)
-> `complete` -> `record_ai_call.execute` -> strict JSON parse (502 on failure).

| | `win_back_note` | `technique_observation` |
|---|---|---|
| Prompt version | `win-back-note-v1` | `technique-observation-v1` |
| Use case | `draft_win_back_note.py` (`DraftWinBackNote`, `PersonaliseWinBackParagraph`) | `draft_technique_observation.py` (`DraftTechniqueObservation`, `DraftTechniqueObservationForStudent`) |
| The model sees | child first name, milestone days (30/60/90), level name, up to 3 `{skill_name, when: YYYY-MM}` wins, academy name | child first name, the coach's typed observation (<= 500 chars, quoted as untrusted), the current level's criteria `{criterion_id, skill_id, skill_name, description}` (<= 40) |
| Output | `{paragraph}` <= 80 words, names the child, no digits but the milestone | `{criterion_id, skill_id, parent_sentence, coach_summary}`; the criterion must be a candidate, the sentence has no digits |
| Human approval | the owner's standing approval: `ai.win_back_personalised` on the academy document (owner-only `GET/PUT /admin/ai/win-back-personalised`, Settings -> Notifications), `ai.win_back_personalised_by` is the `approver` | the coach saving the prefilled note through the existing `POST /coach/students/{id}/skill-notes`; the draft route (`POST .../technique-observation-draft`) stores only the `ai_calls` row |
| Composition | `composition/ai_win_back.py`, hung on `WinBackNotificationAdapter.personaliser`; any AI error logs a WARNING and the templated paragraph goes out | `composition/ai_technique.py` at `app.state.ai_technique` |

Text only: no audio, video or file upload anywhere in this slice (BIPA).
