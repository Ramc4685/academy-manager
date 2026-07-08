# Roadmap Requirements Index

Date: 2026-07-06

This index tracks the requirements docs for the post-launch feature roadmap agreed
after the 2026-07-05 competitive analysis. Each linked doc is self-contained:
problem, requirements, data model, API surface, sequencing, open decisions, and
acceptance criteria. **No code has been written for any of these yet.**

## How to use this set

1. Read a doc fully before scoping implementation work for that item.
2. Cross-doc dependencies are called out in each doc's "Dependencies" section —
   check those before starting, since several billing items share data model
   changes (invoice line types, discount stacking order).
3. "Open Decisions" sections need a product/business call before or during
   implementation — do not guess and build past them.

## Items, in recommended build order

| # | Doc | One-line scope | Depends on |
|---|-----|-----------------|------------|
| 1 | [Registration/annual fee as a charge type](2026-07-06-03-registration-fee-requirements.md) | New first-class fee type charged at enrollment/season start | None |
| 2 | [Promo codes & sibling/family discount automation](2026-07-06-05-promo-codes-sibling-discounts-requirements.md) | Automated discount engine with documented stacking order | #1 (shares invoice line/discount model) |
| 3 | [Consolidated family statement](2026-07-06-02-family-statement-requirements.md) | One rolled-up balance per family across children/enrollments | #1, #2 (statement must reflect fees + discounts correctly) |
| 4 | [Payment plans / installments](2026-07-06-07-payment-plans-installments-requirements.md) | Deposit + installment billing for camps/seasonal programs | #1 (deposit is a fee-type variant) |
| 5 | [Parent self-service: absence/makeup/trial/self-cancel](2026-07-06-01-parent-self-service-requirements.md) | Parent-initiated absence, makeup, trial request, self-cancel | None (touches enrollment/coaching, not billing) |
| 6 | [Smart dunning + ACH-return handling](2026-07-06-09-smart-dunning-ach-returns-requirements.md) | Decline-aware retry timing, split ACH-return path from card declines | None (extends existing `DunningState`/`ACHReturn`) |
| 7 | [Apple Pay / Google Pay + text-to-pay](2026-07-06-08-wallets-text-to-pay-requirements.md) | Enable + market wallets, add SMS/email pay-link flow | Item 6's SMS gap is separate; text-to-pay can ship without full SMS platform |
| 8 | [Self-serve academy signup](2026-07-06-04-self-serve-academy-signup-requirements.md) | Self-serve tenant creation replacing manual platform bootstrap | None (platform/onboarding context) |
| 9 | [Website embeds, iCal sync, accounting export, public API](2026-07-06-06-embeds-calendar-accounting-api-requirements.md) | Ecosystem surface: embeddable widgets, calendar feed, QBO export, public API | Best done after billing items #1-4 settle, since export/API need stable schemas |

Suggested sequencing rationale: billing-adjacent items (#1-4) share a discount/fee
data model, so doing them in that order avoids rework. Parent self-service (#5) and
dunning (#6) are independent and can run in parallel with the billing track. Wallets
(#7) is the cheapest win in the whole roadmap and can be pulled forward if a quick win
is wanted. Self-serve signup (#8) is the highest-leverage growth item but is the
largest single effort — sequence it based on business priority, not technical
dependency. Ecosystem surface (#9) is last because it depends on the billing schemas
settling.

## Source context

All 9 items originated from the 2026-07-05 competitive analysis (14 competitors:
Jackrabbit Class, iClassPro, Sawyer, Upper Hand, LeagueApps, TeamSnap for Business,
CourtReserve, Playbypoint, SportyHQ, Skedda, Omnify, Amilia/SmartRec, TeamUp,
ClassManager) cross-referenced against a read-only inventory of this codebase
(`backend/v2/contexts/*`, `backend/v2/interfaces/*`, `frontend/app/*`). Each
requirements doc below repeats the relevant competitive evidence inline so it can be
read standalone.
