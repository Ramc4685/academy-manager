# AI strategy, Phase 2 build plan

Written 2026-11-04, after Phase 1 shipped to production (PRs #1116, #1117, #1123, #1124, #1125, #1126; run 41918803236). Parent plan: `2026-11-04-ai-strategy.md`, sections 3 to 5 and 9. Phase 2 is the next quarter: the monetization switch-on and the first paid features.

## The gate that shapes the order

The Roast Room conditions the owner accepted say: pre-sell Growth before any AI is built. A card on file by 2026-12-01, charged when the first AI deliverable reaches the academy. No Growth yes by 2026-12-01 means build no AI.

So Phase 2 runs as two tracks. Track A has no model in it and starts now. Track B calls a model and starts only when the owner says in writing that the Growth pre-sale landed, or explicitly waives the gate. The build session stops at the end of Track A and asks.

## What Phase 1 left for Phase 2 to use

- `backend/v2/contexts/ai/`: `LlmPort` with an Anthropic adapter and a disabled adapter, gated by `V2_AI_ENABLED` and `V2_ANTHROPIC_API_KEY` (both off). `record_ai_call` writes `ai_calls` (tenant, feature, prompt version, tokens, cost, approver) and enforces a per-academy monthly cap. Prompt versions live in code (`domain/prompts.py`).
- `has_feature(academy, "ai")` reads `PlatformPlan.features` through the academy's platform subscription.
- `application_fee_bps` exists on billing settings and the Connect gateway path, default 0.
- The non-user send path, lead suppression and CAN-SPAM footer from the acknowledgement slice (#1123).
- The pipeline card's family contact log, the trial to-do list, the 07:30 owner brief, the evening wins and report card templates, the month-close payload, the `Program > Level > Skill > Criterion` shape, the roster import dry-run and commit.

## Track A: money and rules, no model (start now)

Order matters: A1 and A2 are the revenue; A3 is what makes AI usage visible; A4 is the free automation that proves value while waiting on the gate.

### A1. Processing markup per academy

- Per-tenant `application_fee_bps` setting on the tenant record, with agreement acceptance recorded: bps, agreement version, accepted at, accepted by. New academies get 100. The live academy is set to 100 by the owner through the platform UI, not by migration.
- Platform admin UI to view and set it; academy admin sees the rate and the accepted agreement, read-only.
- Agreement text: "core operations free; 12 months notice on any pricing change, applied to new signups first." Never "forever".
- A disclosure line on the academy's payout or statement view showing the platform fee taken. Parents are not charged a per-order fee.
- Connect destination charges read the tenant's bps instead of the global default. Regression test: two tenants, two rates, one charge each.

### A2. Growth tier through Stripe Billing

- `PlatformPlan` rows: Growth at $99 a month with `features: ["ai"]` and 0 bps above the stated volume; Flat at $49 a month for academies under about $5k a month of Stripe volume, decided by the owner per academy, not automatically.
- Stripe Billing checkout from the academy admin's billing page, webhook that creates or updates `TenantSubscription`, cancel at period end honoured by `has_feature` (already handled in #1124).
- Upgrade event instrumented from the first tenant: who upgraded, from what, when, and the Stripe volume at that moment.
- Staging only until the owner approves live Stripe Billing config (production action, explicit approval).

### A3. AI usage meter and free cap

- Admin UI line "you have used X of Y AI drafts this month" reading `ai_calls`. Y comes from the plan: a free-tier cap (owner decision 4; propose 20 a month, soft prompt to upgrade, not a hard stop) and no cap on Growth beyond the abuse ceiling already in the cap code.
- The same meter in the platform admin's tenant view.

### A4. Owner three things and at-risk flag, rules only

- Three ordered lines at the top of the 07:30 brief: failed cards, trial passed but not registered, at-risk families. Fixed rules, no score, no model.
- `at_risk` flag on the family card from the existing attendance and payment signals, with the static 30/60/90 win-back wording unchanged for now.

Track A ends with a report to the owner: what shipped, the Stripe volume pull if the owner shared it, and the question "has the Growth pre-sale landed?"

## Track B: the first AI features (gated)

All Track B slices: `has_feature(academy, "ai")` or the free cap decides access; every call goes through `record_ai_call`; prompts are versioned in code; the model never sees more than the slice states; a human approves before anything reaches a parent. Vendor: the Anthropic adapter already built, on the paid API (no training on API data by default); owner decision 3 on US-only residency stays open and is noted in the DPA, not blocked on.

### B1. Skill-ladder generator (free, adoption)

Owner names a sport and age band; the model drafts levels, skills and observable criteria in the existing shape; the owner edits in the existing curriculum editor before anything is saved. Zero child data. First AI feature because it is the safest and it makes CourtMastr a general academy tool.

### B2. Roster-import copilot (free, adoption)

Maps any spreadsheet to the five import columns, flags bad rows, proposes family grouping. Default mode sends structure only (headers and a few masked sample cells); names go to the model only if the tenant turns that on. The existing dry-run and commit stays the approval gate.

### B3. AI-drafted reply on the pipeline card (paid)

Draft from the inquiry message, child age and class context; staff edit and send with one tap; it logs to the family contact log. Needs a consent line on the inquiry form because free text often carries child details.

### B4. Parent progress narrative with coach review (paid)

Replace the templated sentence in evening wins and the report card with a short specific paragraph citing skill, criteria and the coach's quick-tag words. Coach-review toggle on by default; facts-only prompt; the coach's approval is the `approver` in `ai_calls`.

### B5. Month-close narrator (paid)

Reads the existing month-close payload and odd items, says what happened and what to fix first with links to existing actions. Never computes money; every number in the output must appear in the payload (test for it).

### B6. Win-back wording and text-only technique observations (paid add-on)

Personalise the 30/60/90 win-back with the child's level and last wins. Phase A of technique feedback: the coach types or dictates what they saw, the model maps it to a criterion and phrases it for the parent, coach approves. No video, no audio stored (voiceprint risk under BIPA).

## How the build session runs it

- One worktree off current `origin/main`. One Workflow: Track A slices in dependency order (A1, A2 in parallel on different files; then A3; A4 in parallel with A3), each slice its own agent in isolation, a review agent per PR, a release note per PR in `docs/release-notes/` with the three exact sections and the real PR number.
- Pre-push gate runs in the background; the session does not wait on it in the foreground.
- One PR per slice against `main`. Nothing merges without the owner. Live Stripe or Fly changes need per-action approval.
- After Track A: report and stop. Track B only on the owner's word, then the same pattern, B1 and B2 first.

## Owner actions and open decisions

- Pull the live academy's 90-day Stripe Connect volume by 2026-11-11 and set 100 bps in the platform UI once A1 ships.
- Growth pre-sale: card on file by 2026-12-01. This unlocks Track B.
- Decision 4: free-tier AI cap, proposed 20 drafts a month with a soft upgrade prompt.
- Decision 3: confirm the Anthropic paid API is acceptable as the vendor and whether US-only residency is required.
- Decision 2 (technique pilot with counsel) stays with Phase 3.
