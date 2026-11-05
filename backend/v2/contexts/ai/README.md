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
with a 422 before any model call, in both modes; the error names the column
positions, never the header text, since in a headerless file that is a name. The use case
refuses before spending tokens when the month is at the cap
(`RecordAiCall.assert_under_cap`), records the call before parsing the answer,
and turns an answer that is not the exact JSON shape, repeats a target, lacks
`parent_name` or `student_name`, or names a header not in the file into
`AiProviderError` (502). It reads and writes nothing but the `ai_calls` row.

The human approves in the browser: `FamilyImportPanel` shows the draft as an
editable table, `applyColumnMapping` rewrites the CSV client side, and the
rewritten text goes through the existing import preview and commit, which stay
the only write path for families and students.

### Pipeline reply draft (B3, paid, prompt `pipeline-reply-v1`)

Feature key `pipeline_reply`, prompt `pipeline-reply-v1`,
`application/use_cases/draft_pipeline_reply.py`, wired in
`composition/ai_pipeline.py` behind `POST /admin/pipeline/cards/{id}/reply-draft`.
Order: `has_feature(academy, "ai")` (403 `Ai.NotEntitled`), `assert_under_cap`
(429), the model, `record_ai_call` with the staff member as `approver`, then a
strict parse (502). The model sees exactly `PipelineReplyInput`: academy name,
staff first name, the lead's own message (labelled untrusted, at most 2000
characters), the child's age as stored, the requested class title, up to six
public class lines (name, schedule, price only when the public page shows
prices), the trials-open line and the public page URL. Never the parent's
name, email, phone, notes or another family (`tests/unit/test_ai_pipeline_reply.py`).
The human approval is `POST /admin/pipeline/cards/{id}/reply`
(`crm/application/use_cases/send_pipeline_reply.py`): the edited text goes to
the lead through the prospect send path and is logged on the family contact
log; the draft itself is written nowhere.

### Win-back wording and text-only technique observations (B6, paid)

Two features behind `AiEntitlement.has_ai()` (`has_feature(academy, "ai")`),
each in order: entitlement (403 `Ai.NotEntitled`) -> `assert_under_cap` (429)
-> `complete` -> `record_ai_call.execute` -> strict JSON parse (502 on failure).

| | `win_back_note` | `technique_observation` |
|---|---|---|
| Prompt version | `win-back-note-v1` | `technique-observation-v1` |
| Use case | `draft_win_back_note.py` (`DraftWinBackNote`, `PersonaliseWinBackParagraph`) | `draft_technique_observation.py` (`DraftTechniqueObservation`, `DraftTechniqueObservationForStudent`) |
| The model sees | child first name, milestone days (30/60/90), level name, up to 3 `{skill_name, when: YYYY-MM}` wins, academy name | child first name, the coach's typed observation (<= 500 chars, quoted as untrusted), the current level's criteria `{criterion_id, skill_id, skill_name, description}` (<= 40) |
| Output | `{paragraph}` <= 80 words, names the child, no digits but the milestone, nothing link-like (`://`, `www.`, `@`, bare domains) | `{criterion_id, skill_id, parent_sentence, coach_summary}`; the criterion must be a candidate, the sentence has no digits |
| Human approval | the owner's standing approval: `ai.win_back_personalised` on the academy document (owner-only `GET/PUT /admin/ai/win-back-personalised`, Settings -> Notifications), `ai.win_back_personalised_by` is the `approver` | the coach saving the prefilled note through the existing `POST /coach/students/{id}/skill-notes`; the draft route (`POST .../technique-observation-draft`) stores only the `ai_calls` row |
| Composition | `composition/ai_win_back.py`, hung on `WinBackNotificationAdapter.personaliser`; any AI error logs a WARNING and the templated paragraph goes out. The model is called before the sender's suppression and preference gates, so a suppressed parent still costs one cap slot | `composition/ai_technique.py` at `app.state.ai_technique`; `GET /coach/ai/status` -> `{enabled}` (a model is wired) is what the coach shell gates the draft box on, since a coach-only user cannot read the admin status route |

Text only: no audio, video or file upload anywhere in this slice (BIPA).

### Parent progress narrative (B4, paid, prompt `progress-narrative-v1`)

Feature key `progress_narrative`, prompt `progress-narrative-v1`, `max_tokens`
400. A coach taps "Draft tonight's note" on a student who mastered a skill
today (`POST /api/v2/coach/students/{id}/narrative-draft`). The use case
`DraftProgressNarrative` runs entitlement (`AiNotEntitled`, 403) -> monthly cap
(429) -> `llm.complete` -> `record_ai_call.execute` -> strict parse (502). The
model sees exactly `ProgressNarrativeInput`: the child's first name, level and
program names, today's skills with their observable criteria and the coach's
quick-tag words, and the passed/total counts. No surname, family, attendance
or other children. The draft is stored in `ai_narratives` (tenant-scoped, one
row per `(student_id, for_date, kind)`, migration 0224) as `pending_review`.
The coach edits and approves or rejects it (`PUT
/api/v2/coach/narratives/{id}/decision`); approving sets `approver` to the
coach's user id on both the narrative and its `ai_calls` row (`call_id`). The
evening wins email uses an approved paragraph in place of its templated skill
sentence and ignores pending or rejected rows, so it never waits on review. The
row carries a `source_fingerprint` (sha256 of the sorted skill name/coach words
pairs and the passed/total counts); the email recomputes it from that night's
wins and falls back to the templated sentence when they no longer match. `GET
/api/v2/coach/students/{id}/narrative?date=` returns the day's row (404 when
none) so the workspace restores a draft after a refresh.
`ai.coach_review_narratives: false` on the academy document stores drafts
approved with approver `coach_review_off` (no UI yet).

### Month-close narrator (B5, paid, owner-only, prompt `month-close-narrator-v1`)

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

## Usage meter

Phase 2 slice A3. `application/use_cases/get_ai_usage.py::GetAiUsage`
reports `used` (this UTC month's `ai_calls` rows for the academy in scope),
`tier` (`growth` when the plan has the `ai` feature, else `free`), `cap`
(`FREE_TIER_MONTHLY_DRAFTS` = 20 on free, the academy's `monthly_call_cap`
on Growth) and `upgrade_suggested` (free tier at or past its cap). The free
cap is a soft prompt only (owner decision 4): `RecordAiCall` and its hard
ceiling are unchanged. The entitlement comes through the `EntitlementSource`
port, implemented in `composition/ai_usage.py::ScopedHasFeature` over the
platform billing `HasFeature` use case, so this context still does not import
`platform`. Routes: `GET /api/v2/admin/ai/usage` (admin persona) and
`GET /api/v2/platform/academies/{academy_id}/ai-usage` (platform admin,
enters `tenant_scope`, 404 for an unknown academy); wired at
`app.state.ai_usage`.
