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

## Features

### Roster-import copilot (Phase 2 slice B2)

Feature key `roster_import_map`, prompt `roster-import-map-v1`
(`domain/prompts.py`), use case `application/use_cases/map_import_columns.py`,
route `POST /admin/imports/families/map-columns` (`interfaces/admin/ai_import_routes.py`,
admin persona, same body and size guard as the import preview), wired by
`composition/ai_import.py` at `app.state.ai_import`.

The model proposes ONLY the column mapping from a spreadsheet's headers to the
five import columns. It sees the header row, at most five data rows and the
five target columns with their rules, built from an explicit sample dataclass
and never from a request dict or a stored document. By default every sample
cell is masked to its shape (letters `a`/`A`, digits `9`, cut to 24 characters);
real sample cells go only when the academy's `ai.share_import_values` is true,
set by the owner through `PUT /admin/ai/import-sharing` (Settings >
Notifications, "AI import helper"). Headers go as written unless, in masked mode,
one looks like data (an "@", a run of 4+ digits or an ISO date in any header means
the file has no header row, so every column is relabeled "(column N)"; a header
over 40 characters relabels itself); the answer is translated back to the file's
header names. Two columns with the same name (case and spaces aside) are refused
with a 422 before any model call, in both modes. The use case
refuses before spending tokens when the month is at the cap
(`RecordAiCall.assert_under_cap`), records the call before parsing the answer,
and turns an answer that is not the exact JSON shape, repeats a target, lacks
`parent_name` or `student_name`, or names a header not in the file into
`AiProviderError` (502). It reads and writes nothing but the `ai_calls` row.

The human approves in the browser: `FamilyImportPanel` shows the draft as an
editable table, `applyColumnMapping` rewrites the CSV client side, and the
rewritten text goes through the existing import preview and commit, which stay
the only write path for families and students.
