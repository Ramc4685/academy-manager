# AI strategy for CourtMastr Academy Manager

Date: 2026-11-04. Status: proposal for the owner. Nothing here is built or scheduled.

How this was produced: three agents read `origin/main` (commit 6325c0ebd) for the coaching and progress data, the lead and communications surfaces, and the platform and billing plumbing; three agents researched competitors, the feasibility and legal limits of video technique feedback for minors, and go-to-market evidence for free-first vertical SaaS; one agent synthesised a ranked plan and one tried to refute it. The eight raw memos, with file references and source URLs, are in `docs/plans/2026-11-04-ai-strategy/`. This document is the owner-facing conclusion and takes the skeptic's corrections into account.

## 1. The short version

**How might we** make a free academy-management product feel noticeably smarter than Jackrabbit, iClassPro and Sawyer in an academy's first week, using the roster, attendance, skill-progress and lead data it already captures, so academies adopt it free, keep students longer because parents see progress and leads get answered in minutes, and then pay for a tier built on AI lead handling and owner insight, while never putting a model between a coach and a child and never sending a child's data to a model without a parent's recorded consent.

Five conclusions:

1. **The product has the data for AI, but no AI plumbing at all.** There is no model client, prompt store, audit log, consent flag, per-tenant quota or feature-flag read path. The `openai` pin in `backend/requirements.txt` is unused. Any AI work starts with a small, boring foundation (section 4, Phase 1).
2. **Most of what will win adoption in the next quarter is automation, not AI.** Closing the lead-conversion write, an instant acknowledgement to every inquiry, trial reminders and no-show follow-ups, criterion quick-tags for coaches. The code already has the schedulers, idempotent send claims and pipeline stages to do it. Label these honestly; do not spend an LLM on a merge field.
3. **Technique and posture feedback is the one genuine white space and it is not automatable yet.** No academy platform ties video feedback to a student's level, coach review and a parent report. But frontier video models score near chance on fine-grained movement quality, pose models are trained on adults, and Illinois BIPA plus the amended COPPA rule make children's video a consent-and-retention project before it is a model project. Verdict: pilot narrowly with a coach in the loop; build the text-only version first.
4. **The biggest gap in the plan as the owner framed it is distribution for CourtMastr itself.** "Free until lots of users" only works if there is a channel to get users. There is none today: no racquet-club or coach-community channel, no referral mechanic between academies, no "powered by" link on the public tenant page or parent emails, and a cutover from an incumbent that costs an academy a weekend. Switching cost beats "free".
5. **The monetization model needs one decision.** The owner's stated plan (free now, charge later) conflicts with the September roadmap decision (flat monthly fee via Stripe Billing) and with the strongest comparables in this niche (free software, paid payments: PushPress, Recess, Sawyer charge $0 for software and earn a markup on processing, then sell a Growth tier that lowers the rate and bundles AI). Section 5 lays out the choice.

## 2. What the product already has that AI can stand on

From the code memos (paths relative to `origin/main`, `BE` = `backend/v2/contexts`):

- **Structured progress data with a parent-visibility gate.** Skill status machine (`NOT_STARTED` to `PASSED`/`NEEDS_REVIEW`) with timestamps and a 140-character coach note (`BE/student_progress/domain/models.py:10-18, 85-101`); test attempts with score, pass/fail and override (`:104-126`); coach notes with `private`/`shared` visibility and assistant coaches unable to share (`BE/coaching/application/use_cases/session_notes.py:58-67, 181-186`). That visibility flag is the review-before-parent gate every AI drafting feature needs, and it exists today.
- **Curriculum as one-line observable criteria** such as "Thumb is flat on back of handle" (`BE/curriculum/domain/models.py:92-123`), 22 lesson cards with teaching points and YouTube refs (`contexts/curriculum/content/badminton_lesson_cards.json`), a pace estimate (`BE/student_progress/domain/logic.py:71-89`) and the parent journey view (`get_parent_journey.py`). The criteria are exactly the vocabulary a model should be constrained to.
- **Templated parent and coach comms** that are the obvious first LLM targets: evening wins (`BE/communications/application/parent_wins.py:70-99`), monthly report card (`parent_report_card.py:91-97`), parent and coach digests, win-back copy (`composition/win_back.py`), all behind idempotent send claims, an outbox, and a gated Resend adapter with unsubscribe and bounce suppression.
- **A lead funnel with the right shape and two holes.** Public trial form routed to trial or lead by seat availability (`backend/v2/interfaces/public/trial_request_routes.py:191-197`), `crm_contacts` with consent flags, pipeline columns `inquiry -> trial_booked -> trial_done -> registered -> enrolled` (`BE/crm/domain/pipeline.py:32-69`), daily jobs for trial follow-ups, win-back 30/60/90, waitlist and dues (`backend/v2/main.py:300-318`). Holes: registration approval never writes `enrolled` on the contact, so "inquiry conversion by source" reports 0%, and nothing is sent to the family at inquiry time.
- **Deterministic owner reporting that is safe to narrate.** Month close with `odd` checks and warnings (`BE/billing/application/month_close.py:344-403`), billing health verdict, owner daily brief probes at 07:30 (`backend/v2/shared/observability/owner_daily_brief.py`), people reports, inbox counts.
- **Half-built platform plumbing.** `application_fee_bps` on destination charges, live but 0 (`BE/billing/domain/billing_settings.py:77`); `PlatformPlan` and `TenantSubscription` with a Stripe price id but no checkout or webhook; a parallel `Tenant.plan_code`/`TenantLimits` never fed real usage. Two plan models, neither enforced.
- **Consent machinery** in `contexts/onboarding` (waivers, e-sign) and a gallery-photo consent boolean, plus a JPEG-only 5 MB media pipeline to Firebase Storage. No student photo or video upload exists anywhere.

## 3. Ranked opportunities

Ranked by value to adoption and to later charging, divided by effort. "Automation" means build it without a model. The skeptic's demotions are applied.

| # | Opportunity | Persona | AI or automation | Effort | Free or paid |
|---|---|---|---|---|---|
| 1 | **Close the lead loop.** Write `enrolled` and the linked family on registration approval so conversion reports stop reading 0%. Count "marked contacted" as self-reported response, and say so. Skip UTM fields until a tenant runs ads. | Owner | Automation | S | Free |
| 2 | **Instant acknowledgement to every inquiry** with class, seat band and a booking link. Needs a send path for non-users (`ResolvedRecipient` requires `user_id`), email-keyed suppression, lead unsubscribe and a CAN-SPAM footer, and a decision on sending from the platform domain under each academy's name. | Owner, parent | Automation | M | Free |
| 3 | **Trial pipeline nudges.** Reminder before an approved trial, no-show re-engagement, a drafted message on the existing "trial passed, not registered" to-do, abandoned-checkout recovery. Reuses the scheduler and idempotent follow-up job. Shares the non-user send path with #2. | Owner, parent | Automation | M | Free |
| 4 | **Coach criterion quick-tags with templated sentences.** Tap "thumb flat" and the 140-character win note writes itself. Measure notes per session. Add LLM polish only if coaches ask. The bottleneck is opening the app courtside, not composing prose. | Coach | Automation first | S | Free |
| 5 | **Roster-import copilot.** Map any spreadsheet to the five import columns, fix bad rows, propose family grouping; the existing dry-run and commit is the approval gate. Ranked higher than the strategist had it because switching cost is the adoption barrier. Pair with a hand-done migration service for the first academies. | Owner | AI, no child data to a model beyond names if the tenant consents; can run on structure only | M | Free |
| 6 | **Skill-ladder generator for a new sport.** Owner names the sport and age band; the model drafts levels, skills and observable criteria in the existing `Program > Level > Skill > Criterion` shape; the owner edits before it is saved. Turns a badminton tool into a general academy tool with zero child data. The critic's best addition. | Owner | AI | M | Free |
| 7 | **Owner "three things today."** Three ordered lines in the existing 07:30 brief: failed cards, trial-passed-not-registered, at-risk families. Fixed rules, no score. A narrative version later, if anyone asks. | Owner | Automation | S | Free |
| 8 | **AI-drafted personal reply on the pipeline card.** Uses the inquiry message, child age and class context; staff send with one tap and it logs to `family_contact_log`. Needs a consent line on the form because the free text often carries child details. Worth doing after #2 proves the channel. | Owner | AI | S after #2 | Paid |
| 9 | **Parent progress narrative.** Replace templated sentences in evening wins and the report card with a short specific paragraph citing skill, criteria and the coach's words; coach-review toggle on by default; facts-only prompt. Retention, not acquisition. | Parent | AI | S-M | Paid |
| 10 | **Month-close narrator.** Read the existing month-close payload and odd items and say what happened and what to fix first, with links to existing actions. Never computes money. | Owner, billing | AI | S | Paid |
| 11 | **Churn flag and personalised win-back.** Surface `at_risk` on the family card with a drafted check-in; make the static 30/60/90 win-back cite the child's level and last wins. Rules plus wording; a trained model is not honest with one tenant. | Owner | Automation flag, AI wording | S flag, M copy | Flag free, copy paid |
| 12 | **Technique observations, coach in the loop.** Phase A: coach types or dictates what they saw, the model maps it to a criterion and phrases it for the parent. Phase B: short side-on drill clip, pose on device with face landmarks dropped, up to three criterion-tied observations with a "can't tell" option, coach approves, raw clip auto-deleted. See section 6. | Coach, parent | AI | A: S, B: L | Paid add-on |

Things that were considered and belong in the "not doing" list are in section 8.

## 4. Sequenced phases

### Phase 1, next six weeks: foundations, no model near a parent or a child

- Multi-tenant blockers first, because they gate academies two and three regardless of AI: the global unique indexes that break onboarding from copied data (memory: #849), the hand-applied prod migrations and the boot flag, and a plan for the per-host Firebase redirect in `tenant-host-onboarding.md`.
- #1 conversion write. #2 acknowledgement and #3 trial nudges, templated, with the prospect send path built once. Decide the email category and sender identity for prospects.
- #4 criterion quick-tags.
- AI foundation: one `LlmPort` with one adapter on a paid, no-training tier; prompt versions in code; an `ai_calls` audit collection (tenant, feature, tokens, cost, approver); a per-tenant monthly counter and cap; one plan model kept (retire either `Tenant.plan_code` or `PlatformPlan`) with a `has_feature(academy, X)` read path; remove the dead `openai` pin. This is also the usage metering the platform memo says is missing, scoped to AI.
- Legal groundwork: a data-processing agreement template and a published subprocessor list naming the model vendor; an AI clause and a separate per-child AI/video opt-in in the waiver flow, stored and unused; counsel review of both.
- Distribution groundwork: "powered by CourtMastr" on the public tenant page and parent email footers, a referral link per academy, and a list of the first ten target academies with a named channel for each.

### Phase 2, next quarter: the first paid features

- #5 roster-import copilot and #6 skill-ladder generator (both free, both adoption).
- #7 three lines in the owner brief. #8 AI-drafted reply. #9 parent narrative with coach review. #10 month-close narrator. #11 at-risk flag with drafted check-in.
- #12 Phase A, text only.
- Monetization switch-on per section 5: `application_fee_bps` for new academies first (the field and gateway path exist; add the per-tenant setting, agreement acceptance and a fee line parents can see), then Stripe Billing checkout and webhook for the flat Growth fee, plus "you have used X of Y AI drafts" in the admin UI. Instrument free-to-Growth upgrade rate from the first tenant.

### Phase 3, later

- Auto-send and nurture for leads with marketing consent; app-sent SMS and WhatsApp only through official APIs (10DLC, WhatsApp Cloud API), never the unofficial OpenWA pilot.
- Constrained "ask the academy" over the existing report endpoints as the only tools, once the cost cap and a tool-schema layer exist.
- #12 Phase B video pilot at one academy, under the Phase 1 consent design, only if the accuracy test in section 7 passes.
- Campaign and public-page copy generation (table stakes, cheap, low differentiation).

## 5. Monetization: decided 2026-11-04, model C

Owner decision, 2026-11-04: **model C, free software plus a processing markup and a Growth tier.** This supersedes the September 2026 roadmap decision of a flat monthly fee first. The three models that were on the table, kept for the record:

| Model | What it means | Evidence for | Evidence against |
|---|---|---|---|
| A. Free now, subscription later (owner's stated plan) | $0 for everyone until there are many academies, then introduce a monthly fee. | Simplest message today. | SaaStr: pure freemium needs very large user bases. Wave's 2024 switch from free to tiered drew "features removed" complaints. Every academy that joined free will feel the change. |
| B. Flat monthly fee via Stripe Billing (September roadmap decision) | Software has a price from the first paying academy; `PlatformPlan` and `TenantSubscription` already exist. | Predictable revenue; market prices small academies at $50-200/month without AI, $250-550 with. | Hardest to pitch against incumbents the academy already pays; no free motion at all. |
| C. Free software, paid payments, plus a Growth tier (the research recommendation) | $0 forever for rosters, attendance, billing and the parent app; about 1% markup on Stripe Connect processing; a flat Growth fee that lowers the rate and bundles AI. `application_fee_bps` exists and is 0. | PushPress, Recess, Sawyer run this in this niche; no "we are now charging" moment; grows with the academy; AI is the natural paid differentiator. | Only earns when academies run payments through the platform; many small academies take Zelle, Venmo, cash or the old processor. A total rate near 3.9% gets compared directly with incumbents. 1% of a $20k/month academy is about $200/month. |

What C means in practice: core operations (rosters, attendance, billing, parent app, pipeline board, templated comms) are free forever and that list is the written contract with every academy; the markup is `application_fee_bps` on Stripe Connect destination charges, default 0 today, set to roughly 100 bps for new academies from Phase 2 and recorded on the tenant record with agreement acceptance; the Growth tier is a flat monthly fee through `PlatformPlan` and Stripe Billing that lowers the rate above a stated monthly volume and bundles the AI features in section 3; no per-order fee is charged to parents by default; any later price change applies to new signups first with 12 months of grandfathering. Owner accepted the Roast Room conditions below on 2026-11-04; they are the plan of record. Roast Room council verdict, 2026-11-04 (GO WITH CONDITIONS, C scored 7.3 vs B 5.2, A 2.0; verdict at `~/Documents/Code/roast-room/sessions/2026-11-04-courtmastr-monetization/verdict.md`): keep C with four changes. Markup is 100 bps, not more, because 4.4% all-in invites the Zelle comparison and a rate is easier to raise for new signups than to cut. Growth is $99 a month at 0 bps, so it pays for itself above about $10k a month of Stripe volume. The agreement says "core operations free; 12 months notice on any pricing change, applied to new signups first" and never "forever", which keeps the offer two-way. The live academy pays 100 bps from day one. Any academy under about $5k a month through Stripe is offered a flat $49 instead, because below that a flat fee earns more and teaches more. Pre-sell Growth before any AI is built: a card on file by 2026-12-01, charged when the first AI deliverable (which may be done by hand) reaches the academy. Cheapest test: pull the live academy's 90-day Stripe Connect volume by 2026-11-11; if it is under $5k a month, model B is the honest model for that academy. Kill criteria: pushback on 100 bps means stop before academy two and rethink; no Growth yes by 2026-12-01 means build no AI. Minority report (Graham): pricing is not the bottleneck, weeks to the first real second academy is; he would list Growth at $149, waive it for the live academy for 12 months in exchange for a testimonial and three intros, and spend the time calling clubs.

## 6. Technique and posture feedback: verdict

**Pilot, narrowly. Not "build now" as a product feature, and not "no".**

Why it is worth pursuing: no academy or class platform ties technique feedback to roster, level, coach review and a parent report. Pose apps such as goSmash and SwingVision are player-side and disconnected from operations. If it works, it is the feature academies cannot get elsewhere, and it is the owner's stated first interest.

Why the automatic version is not feasible yet: frontier video models score only marginally above chance on action quality (arXiv 2604.08294); on the FineBadminton benchmark Gemini 2.5 Pro reached 22% and GPT-4.1 30% on stroke classification; Gemini samples video at one frame per second by default; pose models are trained on adults and degrade on children, with no published study on children in racquet sports; reliable contact point, racket-face angle or grip from 30 fps phone video is not available. So the model may propose, the coach decides, and the parent sees only approved text.

Legal constraints that shape the design:

- **Illinois BIPA.** Biometric identifiers are retina, iris, fingerprint, voiceprint, and hand or face geometry; photographs are excluded; no case was found on body-only pose. Damages remain $1,000 or $5,000 per person after SB 2979. Design rules: never run face detection or recognition, drop the facial landmarks from the MediaPipe 33-point set, never auto-identify which child is in a clip, publish a retention schedule, obtain a written electronic release per child. Coach dictation adds voiceprint exposure and coaches are a plaintiff class, so any speech-to-text vendor must confirm no voiceprint is created and audio is not retained, with a coach release.
- **COPPA, amended rule in force since 2026-04-22.** Biometric identifiers now include gait patterns; a child's skeleton time series is arguably adjacent. Requires verifiable parental consent before collection, a written retention policy with a deletion timeline, naming the AI vendor as a third party, and letting parents consent to collection without consenting to disclosure. The critic notes COPPA mainly bites when data is collected from the child; here the parent and coach supply it, so the stricter practical constraints are BIPA, CAN-SPAM for prospect email, TCPA and 10DLC before any SMS, Illinois SOPPA if a school contract is ever signed, and other states' minor-privacy laws as tenants appear outside Illinois.
- **Vendor terms.** Children's clips only go to a paid no-training tier. Cost is not the constraint at roughly $0.003 to $0.07 per clip; storage, egress and coach time are.

Pilot rules: per-child opt-in separate from the waiver, naming the vendor; side-on single-stroke drill clips of 10-20 seconds at 60 fps; pose on device with only candidate frames and joint angles leaving the phone; raw clip deleted within 30-90 days; coach approval before any parent sees anything; counsel reviews the consent text before the first clip; if coaches accept fewer than about half of the observations unedited, drop the model step and keep dictation plus rewriting.

## 7. Assumptions and how to test them cheaply

The data is small. One tenant and a handful of coaches cannot produce statistically meaningful accept rates, so most of these are decided on qualitative signal from two or three owner interviews, not metrics.

| Assumption | Test |
|---|---|
| Academies will adopt free operations software from a one-tenant vendor. | Hand-onboard two academies with the runbook before writing self-serve signup. If neither says yes in six weeks, the problem is not AI. The owner's RoboThink business is a natural non-badminton pilot, subject to the franchise agreement. |
| Speed-to-lead matters in this niche, where parents text and DM rather than fill in forms. | Ask the two pilot owners how leads arrive and how they answer today. Treat "marked contacted" as self-reported. |
| Coaches will use quick-tags courtside. | Ship #4; count notes per session before and after; ask the coaches. |
| Parents read progress emails and it moves retention. | `message_deliveries.opened_at` on evening wins today; after #9, compare narrative versus templated open rates. |
| Owners accept a processing markup or a flat Growth fee. | Fake-door a priced Growth tier on the platform landing page; ask the pilot owners to pick; flip `application_fee_bps` for one new academy and watch for pushback. |
| Pose estimation separates pass from fail on Level 1-2 criteria for 5-14-year-olds. | Before any upload UI: 20 side-on clips with written consent through MediaPipe on a laptop; a coach labels the criteria; compare. If elbow and knee angles cannot separate grip and lunge pass from fail, Phase B waits. |
| One vendor's paid tier satisfies "no training on children's data" and counsel. | Read the data-use terms for Anthropic and Google paid tiers; one page to counsel with the consent draft. |

## 8. Not doing, and why

- Any AI that writes directly to parents or judges a child without a coach or staff approval step. Accuracy evidence is poor and the consent base does not exist.
- A trained churn or lead-scoring model. One tenant, few departures, no outcome labels.
- Face detection, recognition or auto-tagging of children in media. Direct BIPA exposure for no product gain.
- Unofficial WhatsApp as a product channel. Fine as the owner's own pilot, unusable for other academies.
- AI website builder and ad-creative generation now. Table stakes at TeamSnap, Sawyer and Mindbody; weak independent evidence; sub-$50/day budgets produce noise.
- Natural-language reporting now. No tool-schema layer and no AI cost cap yet.
- Schedule-conflict AI. No court, room or coach availability model to reason over.
- A per-order fee charged to parents by default. Parents are cost-stressed and Sawyer's fee drew complaints.
- Paid tiers for personalised trial nudges or a narrative owner brief. Nobody upgrades for a merge field or a reworded list.

## 9. Decisions needed from the owner

1. Decided and accepted 2026-11-04: model C with the Roast Room conditions (section 5): 100 bps, Growth $99 at 0 bps, flat $49 under $5k a month, 12 months notice instead of "forever", live academy pays from day one. Owner actions with dates: pull 90-day Stripe volume and set 100 bps by 2026-11-11; Growth pre-sale card on file by 2026-12-01; review 2027-02-01.
2. Is BLNO willing to be the technique-feedback pilot, including paying counsel to review a per-child AI/video consent and retention policy before the first clip?
3. Which model vendor, given children's data may only go to a paid no-training tier, and is US-only data residency required?
4. Monthly AI cap for the free tier per academy, and hard stop or soft "upgrade" prompt.
5. For the first five academies, accept the manual Firebase console step per host, or hold self-serve signup until the per-host redirect is removed?
6. May the platform email a prospect who is not a user, from the platform domain under the academy's display name, on the strength of the form's "contact me about this request" tick alone?
7. Who is the first channel for CourtMastr's own leads: USA Badminton club directory, local racquet clubs, coach communities, the owner's own second business, or something else?

## Appendix: memos

All in `docs/plans/2026-11-04-ai-strategy/`:

- `memo-coaching.md`: coaching, student progress and curriculum data on `origin/main`, with file references.
- `memo-crm.md`: lead, enrollment and communications surfaces.
- `memo-platform.md`: platform, billing and tenant plumbing; free-then-paid readiness.
- `memo-competitors.md`: AI features and pricing at 15 vendors, 48 sources.
- `memo-technique.md`: feasibility, models, BIPA and COPPA, cost per clip, MVP shape.
- `memo-gtm.md`: free-first evidence, monetization comparables, AI lead-gen evidence, what parents care about, 55 sources.
- `memo-synthesis.md`: the strategist's full ranked plan before the critique.
- `memo-critique.md`: the skeptic's verdicts and the ten things the strategy missed.

Not verified in this pass: BLNO's real lead volume and coach count, how BLNO takes payments today, the exact BIPA section 15(b) wording, and whether any competitor has these features in private beta. Legal points are an operator's reading and need counsel.
